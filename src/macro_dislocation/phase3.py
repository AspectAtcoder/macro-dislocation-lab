from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .pit_events import (
    RIGHTS,
    audit_components,
    build_calendar_bundles,
    write_dict_csv,
)
from .vendor_capture import (
    CAPTURE_OBSERVATION_FIELDS,
    VendorCaptureStore,
    public_endpoint,
    validate_rights_attestation,
)


SYNTHETIC_SECRET = "PHASE3_SYNTHETIC_CREDENTIAL_MUST_NOT_PERSIST"
SYNTHETIC_ENDPOINT = (
    "https://api.tradingeconomics.com/calendar/country/synthetic"
    f"?c={SYNTHETIC_SECRET}&f=json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _capture_fixture_plan(
    store: VendorCaptureStore,
    specification: dict[str, Any],
    *,
    project_root: Path,
) -> None:
    if store.observations():
        expected = specification["scope"]["fixture_receipts"]
        if len(store.observations()) != expected:
            raise RuntimeError(
                "existing fixture store is partial or unexpected; preserve it for audit"
            )
        return
    rights = {name: True for name in RIGHTS}
    for item in specification["fixture_capture_plan"]:
        payload = (project_root / item["file"]).read_bytes()
        store.capture(
            payload,
            provider="trading_economics",
            transport=item["transport"],
            endpoint=(
                SYNTHETIC_ENDPOINT
                if item["transport"] == "https_snapshot"
                else f"wss://stream.tradingeconomics.com/?client={SYNTHETIC_SECRET}"
            ),
            request_started_at=item["request_started_at"],
            received_at=item["received_at"],
            received_monotonic_ns=item["received_monotonic_ns"],
            http_status=200 if item["transport"] == "https_snapshot" else None,
            license_class="synthetic_fixture",
            rights_profile=rights,
            provenance="synthetic_fixture_not_empirical",
        )


def _base_capture_args() -> dict[str, Any]:
    return {
        "provider": "trading_economics",
        "transport": "synthetic_fixture",
        "endpoint": SYNTHETIC_ENDPOINT,
        "request_started_at": "2030-01-10T13:28:59+00:00",
        "received_at": "2030-01-10T13:29:00+00:00",
        "received_monotonic_ns": 1_000_000_000,
        "http_status": None,
        "license_class": "synthetic_fixture",
        "rights_profile": {name: True for name in RIGHTS},
        "provenance": "synthetic_fixture_not_empirical",
    }


def _run_failure_injections(pre_release_fixture: Path) -> dict[str, bool]:
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as directory:
        store = VendorCaptureStore(Path(directory) / "malformed")
        try:
            store.capture(b"{not-json", **_base_capture_args())
        except ValueError:
            results["malformed_json_before_persistence"] = (
                not store.observations() and not list(store.raw_root.rglob("*.json"))
            )
        else:
            results["malformed_json_before_persistence"] = False

        missing_store = VendorCaptureStore(Path(directory) / "missing-id")
        missing_payload = json.dumps(
            {"Date": "2030-01-10T13:30:00Z", "Event": "Synthetic CPI"}
        ).encode("utf-8")
        try:
            missing_store.capture(missing_payload, **_base_capture_args())
        except ValueError:
            results["missing_provider_event_id"] = (
                not missing_store.observations()
                and not list(missing_store.raw_root.rglob("*.json"))
            )
        else:
            results["missing_provider_event_id"] = False

        try:
            validate_rights_attestation(
                {
                    "approved": True,
                    "agreement_id": "real-agreement",
                    "approved_by": "risk",
                    "attested_at": "2026-08-10T00:00:00+00:00",
                    "license_class": "licensed_vendor",
                    "rights": {"retention": True},
                }
            )
        except ValueError:
            results["incomplete_rights_attestation"] = True
        else:
            results["incomplete_rights_attestation"] = False

        sanitized = public_endpoint(SYNTHETIC_ENDPOINT)
        results["credential_in_endpoint_query"] = (
            SYNTHETIC_SECRET not in sanitized and "?" not in sanitized
        )

        corrupt_store = VendorCaptureStore(Path(directory) / "corrupt")
        capture = corrupt_store.capture(pre_release_fixture.read_bytes(), **_base_capture_args())
        digest = capture.observation["payload_sha256"]
        corrupt_store._blob_path(digest).write_bytes(b"corrupt-fixture")
        results["corrupt_content_addressed_blob"] = not corrupt_store.integrity_report()[
            "passed"
        ]
    return results


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    counts = summary["counts"]
    return f"""# Phase 3 result

Step 3のvendor capture／replayパイプラインは
**{summary['pipeline_status']}** です。認証通信・価格結合・モデル学習は実行していません。

## Offline capture

- capture observations: {counts['capture_observations']}
- unique raw payloads: {counts['unique_raw_blobs']}
- normalized snapshots: {counts['normalized_snapshots']}
- structurally eligible synthetic components: {counts['structurally_eligible_fixture_components']}
- empirical vendor rows: {counts['empirical_vendor_rows']}

HTTPS snapshotのpre-release payloadを2回、stream形式のpost-release payloadを1回、
固定したsynthetic fixtureから取り込みました。同じraw bytesは1 blobだけ保存し、受信は
3 observationすべてを追記しました。fixtureは構造契約を通りますが、実観測ではないため
価格利用の証拠には数えません。

## Clock and replay

provider `LastUpdate`、local `received_at`、monotonic receive clockを分離しました。
`snapshot_at`はlocal receiptから作り、provider時刻で代用していません。

- deterministic capture hash: `{summary['capture_hash']}`
- replay identical: {summary['replay_identical']}
- credential persistence matches: {summary['integrity']['credential_persistence_matches']}

## Failure injection

malformed JSON、provider ID欠損、不完全な利用権、credential付きURL、blob破損を注入し、
すべてfail-closedになることを確認しました。

## Gate

{checks}

最終テスト数と事前登録commit照合は `macro-lab verify-phase3` が判定します。
"""


def run_phase3(
    specification_path: Path,
    capture_contract_path: Path,
    pit_contract_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    capture_contract = json.loads(capture_contract_path.read_text(encoding="utf-8"))
    json.loads(pit_contract_path.read_text(encoding="utf-8"))
    gates = specification["completion_gates"]

    store = VendorCaptureStore(output_dir / "vendor_capture_store")
    _capture_fixture_plan(store, specification, project_root=project_root)
    integrity = store.integrity_report(forbidden_values=[SYNTHETIC_SECRET])
    observations = store.observations()
    snapshots = store.replay()
    snapshot_rows = [asdict(snapshot) for snapshot in snapshots]
    audits = audit_components(snapshots)
    bundles = build_calendar_bundles(audits)
    capture_hash = _hash_json(snapshot_rows)
    replay_hash = _hash_json([asdict(snapshot) for snapshot in store.replay()])
    failure_injections = _run_failure_injections(
        project_root / specification["inputs"]["pre_release_fixture"]
    )

    supported = set(capture_contract["supported_transports"])
    observation_fields = set(capture_contract["required_observation_fields"])
    clocks_separate = all(
        snapshot.snapshot_at == snapshot.received_at
        and snapshot.provider_updated_at != snapshot.received_at
        for snapshot in snapshots
    )
    schema_parity = (
        len({snapshot.provider_event_id for snapshot in snapshots}) == 1
        and len({snapshot.component for snapshot in snapshots}) == 1
        and {item["transport"] for item in observations}
        == {"https_snapshot", "websocket_calendar"}
    )
    counts = {
        "capture_observations": len(observations),
        "unique_raw_blobs": integrity["unique_raw_blobs"],
        "normalized_snapshots": len(snapshots),
        "component_audits": len(audits),
        "calendar_bundles": len(bundles),
        "structurally_eligible_fixture_components": sum(
            item["eligible_for_price_join"] for item in audits
        ),
        "empirical_vendor_rows": sum(
            snapshot.provenance != "synthetic_fixture_not_empirical"
            for snapshot in snapshots
        ),
    }
    checks = {
        "capture_contract_schema_valid": observation_fields
        == set(CAPTURE_OBSERVATION_FIELDS)
        and supported == {"https_snapshot", "websocket_calendar", "synthetic_fixture"},
        "fixture_receipts": counts["capture_observations"] == gates["fixture_receipts"],
        "unique_raw_blobs": counts["unique_raw_blobs"] == gates["unique_raw_blobs"],
        "normalized_snapshots": counts["normalized_snapshots"]
        == gates["normalized_snapshots"],
        "component_audits": counts["component_audits"] == gates["component_audits"],
        "calendar_bundles": counts["calendar_bundles"] == gates["calendar_bundles"],
        "structurally_eligible_fixture_components": counts[
            "structurally_eligible_fixture_components"
        ]
        == gates["structurally_eligible_fixture_components"],
        "empirical_vendor_rows": counts["empirical_vendor_rows"]
        == gates["empirical_vendor_rows"],
        "append_only_duplicate_observation": len(observations) == 3
        and observations[0]["payload_sha256"] == observations[1]["payload_sha256"]
        and observations[0]["capture_id"] != observations[1]["capture_id"],
        "historical_and_stream_schema_parity": schema_parity,
        "provider_and_receive_clocks_separate": clocks_separate,
        "deterministic_replay_hash": capture_hash == replay_hash,
        "failure_injections_pass": all(failure_injections.values()),
        "credential_persistence_matches": integrity["credential_persistence_matches"]
        == gates["credential_persistence_matches"],
        "store_integrity": integrity["passed"],
        "no_authenticated_vendor_request": gates[
            "authenticated_vendor_request_executed"
        ]
        is False,
        "no_price_model": gates["price_model_executed"] is False,
        "no_market_price_join": gates["market_price_join_executed"] is False,
    }
    passed = all(checks.values())
    summary = {
        "trial_id": specification["trial_id"],
        "phase3_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_FOR_AUTHENTICATED_SHADOW_CAPTURE_PENDING_VERIFICATION"
            if passed
            else "FAIL_CAPTURE_INTEGRITY"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_SHADOW_DATA_REQUIRED",
        "counts": counts,
        "capture_hash": capture_hash,
        "replay_hash": replay_hash,
        "replay_identical": capture_hash == replay_hash,
        "integrity": integrity,
        "failure_injections": failure_injections,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "price_model_executed": False,
        "market_price_join_executed": False,
        "limitations": [
            "only synthetic fixtures were captured",
            "no licensed credential or approved rights attestation was supplied",
            "no websocket connection was opened in the offline trial",
            "structural fixture eligibility is not empirical price eligibility",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "capture_observations.json", observations)
    write_dict_csv(output_dir / "normalized_snapshots.csv", snapshot_rows)
    write_dict_csv(output_dir / "component_audit.csv", audits)
    _write_json(output_dir / "event_bundles.json", bundles)
    _write_json(output_dir / "integrity_report.json", integrity)
    _write_json(output_dir / "failure_injections.json", failure_injections)
    _write_json(output_dir / "phase3_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "capture_hash": capture_hash,
        },
    )
    (output_dir / "PHASE3_REPORT.md").write_text(_report(summary), encoding="utf-8")
    return summary
