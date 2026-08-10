from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .pit_events import (
    PitSnapshot,
    audit_components,
    build_calendar_bundles,
    bundle_hash,
    load_official_feature_bundles,
    load_research_calendar,
    write_dict_csv,
)


TE_GUEST_PROBE_URL = (
    "https://api.tradingeconomics.com/calendar/country/"
    "united%20states/2024-01-01/2024-01-07?c=guest:guest"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def vendor_preflight(*, timeout: float = 30.0) -> dict[str, Any]:
    credential_name = "TRADING_ECONOMICS_API_KEY"
    credential_present = bool(os.environ.get(credential_name))
    status: int | None = None
    response_sha256: str | None = None
    error: str | None = None
    try:
        request = Request(
            TE_GUEST_PROBE_URL,
            headers={"User-Agent": "macro-dislocation-lab/0.2 data-contract-preflight"},
        )
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = int(response.status)
            response_sha256 = hashlib.sha256(body).hexdigest()
    except HTTPError as exc:
        body = exc.read()
        status = int(exc.code)
        response_sha256 = hashlib.sha256(body).hexdigest()
        error = f"HTTP {exc.code}"
    except Exception as exc:  # pragma: no cover - environment-specific network error
        error = f"{type(exc).__name__}: {exc}"
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Trading Economics",
        "official_pit_documentation": (
            "https://docs.tradingeconomics.com/economic_calendar/point-in-time/"
        ),
        "credential_environment_variable": credential_name,
        "credential_present": credential_present,
        "authenticated_probe_attempted": False,
        "guest_probe_url_without_credentials": TE_GUEST_PROBE_URL.split("?", 1)[0],
        "guest_http_status": status,
        "guest_response_sha256": response_sha256,
        "guest_error": error,
        "empirical_vendor_rows_acquired": 0,
        "note": (
            "Guest response is availability evidence only. No documentation example "
            "or unauthenticated response is counted as empirical PIT data."
        ),
    }


def _report(summary: dict[str, Any], preflight: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    return f"""# Phase 2 result

Phase 2のdata-contract／event-bundleパイプラインは
**{summary['pipeline_status']}** です。価格モデルは実行していません。

## Negative control

- research calendar bundles: {summary['counts']['research_calendar_bundles']}
- research components parsed: {summary['counts']['research_components']}
- price-eligible research components: {summary['counts']['research_price_eligible_components']}
- official feature bundles: {summary['counts']['official_feature_bundles']}
- total bundles: {summary['counts']['total_bundles']}

既存の2024年CPI/NFPカレンダーは全60 componentを正常に読み取りましたが、
pre-release snapshot時刻、consensus vintage証明、利用権が無いため、全件を
価格結合不可と判定しました。これは登録したnegative controlの期待結果です。

## Event bundles

同一の国・通貨・発表時刻を持つcomponentを1 bundleへまとめました。CPIは2 component、
NFPは3 componentです。Phase 1のFOMC 24件とEIA 52件も公式feature bundleとして
統合しましたが、履歴live到着時刻が復元できないため価格利用不可のままです。

- deterministic bundle hash: `{summary['bundle_hash']}`
- replay identical: {summary['replay_identical']}

## Vendor preflight

- credential present: {preflight['credential_present']}
- guest HTTP status: {preflight['guest_http_status']}
- empirical PIT rows acquired: {preflight['empirical_vendor_rows_acquired']}

Trading Economicsのguest経路はHTTP 410で、認証済みPITデータは0件です。したがって
pipelineがPASSしても価格実験はNo-Goです。次に必要なのはAPI契約と、保存・backtest・
ML学習・derived-dataの権利確認です。

## Gate

{checks}

最終テスト数と事前登録commit照合は `macro-lab verify-phase2` が判定します。
"""


def run_phase2(
    specification_path: Path,
    contract_path: Path,
    research_calendar_path: Path,
    phase1_documents_path: Path,
    fomc_features_path: Path,
    eia_features_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    snapshot_fields = {item.name for item in fields(PitSnapshot)}
    contract_schema_valid = set(contract["required_fields"]).issubset(snapshot_fields)

    research_snapshots = load_research_calendar(research_calendar_path)
    component_audits = audit_components(research_snapshots)
    calendar_bundles = build_calendar_bundles(component_audits)
    official_bundles = load_official_feature_bundles(
        phase1_documents_path, fomc_features_path, eia_features_path
    )
    all_bundles = sorted(
        calendar_bundles + official_bundles,
        key=lambda item: (item["scheduled_at"], item["bundle_id"]),
    )
    first_hash = bundle_hash(all_bundles)
    replay_audits = audit_components(load_research_calendar(research_calendar_path))
    replay_calendar = build_calendar_bundles(replay_audits)
    replay_official = load_official_feature_bundles(
        phase1_documents_path, fomc_features_path, eia_features_path
    )
    replay_bundles = sorted(
        replay_calendar + replay_official,
        key=lambda item: (item["scheduled_at"], item["bundle_id"]),
    )
    replay_hash = bundle_hash(replay_bundles)
    preflight = vendor_preflight()

    required_negative_flags = set(
        specification["expected_negative_control"]["required_failures"]
    )
    gates = specification["completion_gates"]
    eligible_components = sum(
        bool(item["eligible_for_price_join"]) for item in component_audits
    )
    counts = {
        "research_snapshots": len(research_snapshots),
        "research_components": len(component_audits),
        "research_calendar_bundles": len(calendar_bundles),
        "research_price_eligible_components": eligible_components,
        "official_feature_bundles": len(official_bundles),
        "fomc_official_feature_bundles": sum(
            item["document_type"] == "fomc_statement" for item in official_bundles
        ),
        "eia_official_feature_bundles": sum(
            item["document_type"] == "eia_wpsr" for item in official_bundles
        ),
        "total_bundles": len(all_bundles),
        "price_eligible_bundles": sum(
            bool(item["eligible_for_price_join"]) for item in all_bundles
        ),
    }
    every_negative_flag_present = all(
        required_negative_flags.issubset(set(item["issues"]))
        for item in component_audits
    )
    pipeline_checks = {
        "contract_schema_valid": contract_schema_valid,
        "research_calendar_bundles": counts["research_calendar_bundles"]
        == gates["research_calendar_bundles"],
        "research_calendar_components": counts["research_components"]
        == gates["research_calendar_components"],
        "research_price_eligible_components": counts[
            "research_price_eligible_components"
        ]
        == gates["research_price_eligible_components"],
        "negative_control_failure_codes": every_negative_flag_present,
        "official_feature_bundles_minimum": counts["official_feature_bundles"]
        >= gates["official_feature_bundles_minimum"],
        "total_bundles_minimum": counts["total_bundles"]
        >= gates["total_bundles_minimum"],
        "simultaneous_components_bundled": (
            sum(item["component_count"] for item in calendar_bundles)
            == counts["research_components"]
            and counts["research_calendar_bundles"] == 24
        ),
        "deterministic_bundle_hash": first_hash == replay_hash,
        "guest_probe_matches_registered_status": preflight["guest_http_status"]
        == specification["vendor_preflight"]["guest_endpoint_expected_status"],
        "no_empirical_vendor_rows_without_auth": preflight[
            "empirical_vendor_rows_acquired"
        ]
        == 0,
        "price_model_not_executed": gates["price_model_executed"] is False,
        "market_price_join_not_executed": gates["market_price_join_executed"]
        is False,
    }
    pipeline_status = (
        "READY_FOR_LICENSED_VENDOR_INGESTION_PENDING_VERIFICATION"
        if all(pipeline_checks.values())
        else "FAIL_DATA_CONTRACT"
    )
    summary = {
        "trial_id": specification["trial_id"],
        "phase2_status": "PIPELINE_EXECUTED",
        "pipeline_status": pipeline_status,
        "decision_if_verified": (
            "READY_FOR_LICENSED_VENDOR_INGESTION"
            if pipeline_status.startswith("READY")
            else "FAIL_DATA_CONTRACT"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_VENDOR_DATA_REQUIRED",
        "counts": counts,
        "bundle_hash": first_hash,
        "replay_hash": replay_hash,
        "replay_identical": first_hash == replay_hash,
        "pipeline_checks": pipeline_checks,
        "price_model_executed": False,
        "market_price_join_executed": False,
        "limitations": [
            "no authenticated PIT vendor rows were available",
            "research calendar lacks captured pre-release consensus timestamps",
            "research calendar retention and ML rights are not proven",
            "official archive feature-ready timestamps are not historical live latency",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_dict_csv(
        output_dir / "normalized_research_snapshots.csv",
        [item.to_dict() for item in research_snapshots],
    )
    write_dict_csv(output_dir / "component_audit.csv", component_audits)
    write_dict_csv(
        output_dir / "bundle_index.csv",
        [
            {
                "bundle_id": item["bundle_id"],
                "bundle_kind": item["bundle_kind"],
                "scheduled_at": item["scheduled_at"],
                "eligible_for_price_join": item["eligible_for_price_join"],
                "issues": item["issues"],
            }
            for item in all_bundles
        ],
    )
    _write_json(output_dir / "event_bundles.json", all_bundles)
    _write_json(output_dir / "vendor_preflight.json", preflight)
    _write_json(output_dir / "phase2_summary.json", summary)
    manifest = {
        "inputs": {
            str(specification_path): _sha256(specification_path),
            str(contract_path): _sha256(contract_path),
            str(research_calendar_path): _sha256(research_calendar_path),
            str(phase1_documents_path): _sha256(phase1_documents_path),
            str(fomc_features_path): _sha256(fomc_features_path),
            str(eia_features_path): _sha256(eia_features_path),
        },
        "bundle_hash": first_hash,
        "trial_id": specification["trial_id"],
    }
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "PHASE2_REPORT.md").write_text(
        _report(summary, preflight), encoding="utf-8"
    )
    return summary
