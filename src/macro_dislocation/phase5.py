from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .evidence_enrollment import (
    EVIDENCE_PACKAGE_FIELDS,
    audit_evidence_package,
    audit_evidence_records,
    campaign_checkpoint,
    load_linked_trace_fixture,
    validate_ledger_candidates,
    vendor_access_preflight,
)
from .pit_events import RIGHTS
from .shadow_campaign import ShadowTraceStore, build_release_plans
from .vendor_capture import CAPTURE_OBSERVATION_FIELDS, VendorCaptureStore


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


def _populate_synthetic_capture_store(
    store: VendorCaptureStore, pre_payload_path: Path, post_payload_path: Path
) -> tuple[str, str]:
    existing = store.observations()
    if not existing:
        rights = {name: True for name in RIGHTS}
        pre = store.capture(
            pre_payload_path.read_bytes(),
            provider="trading_economics",
            transport="https_snapshot",
            endpoint="https://api.tradingeconomics.com/calendar/country/synthetic",
            request_started_at="2030-01-10T13:29:04+00:00",
            received_at="2030-01-10T13:29:05+00:00",
            received_monotonic_ns=81_000_000_000,
            http_status=200,
            license_class="synthetic_fixture",
            rights_profile=rights,
            provenance="synthetic_fixture_not_empirical",
        )
        post = store.capture(
            post_payload_path.read_bytes(),
            provider="trading_economics",
            transport="websocket_calendar",
            endpoint="wss://stream.tradingeconomics.com/",
            request_started_at="2030-01-10T13:30:00+00:00",
            received_at="2030-01-10T13:30:00.800000+00:00",
            received_monotonic_ns=136_800_000_000,
            http_status=None,
            license_class="synthetic_fixture",
            rights_profile=rights,
            provenance="synthetic_fixture_not_empirical",
        )
        return pre.observation["capture_id"], post.observation["capture_id"]
    if len(existing) != 2:
        raise RuntimeError(
            "existing Phase 5 capture store is partial; preserve it for audit"
        )
    by_transport = {str(item["transport"]): item for item in existing}
    if set(by_transport) != {"https_snapshot", "websocket_calendar"}:
        raise RuntimeError(
            "existing Phase 5 capture store differs from the registered fixture"
        )
    store.replay_index()
    return (
        str(by_transport["https_snapshot"]["capture_id"]),
        str(by_transport["websocket_calendar"]["capture_id"]),
    )


def _run_failure_injections(
    plan: Any,
    trace: list[dict[str, Any]],
    store: VendorCaptureStore,
    policy: dict[str, Any],
    expected: dict[str, str],
) -> dict[str, dict[str, Any]]:
    observations = store.observations()
    snapshots = {
        capture_id: [asdict(snapshot) for snapshot in values]
        for capture_id, values in store.replay_index().items()
    }
    integrity = store.integrity_report()

    def audit(value: list[dict[str, Any]]) -> dict[str, Any]:
        return audit_evidence_records(
            plan,
            value,
            observations,
            snapshots,
            integrity,
            policy,
        )

    traces: dict[str, list[dict[str, Any]]] = {}
    missing = json.loads(json.dumps(trace))
    for event in missing:
        if event["kind"] == "pre_snapshot_captured":
            event["details"].pop("capture_id", None)
    traces["missing_capture_reference"] = missing

    unknown = json.loads(json.dumps(trace))
    for event in unknown:
        if event["kind"] == "pre_snapshot_captured":
            event["details"]["capture_id"] = "0" * 64
    traces["unknown_capture_id"] = unknown

    drift = json.loads(json.dumps(trace))
    for event in drift:
        if event["kind"] == "pre_snapshot_captured":
            event["observed_at"] = "2030-01-10T13:29:06+00:00"
    traces["capture_trace_clock_drift"] = drift

    claim = json.loads(json.dumps(trace))
    for event in claim:
        if event["kind"] == "store_audit":
            event["details"]["observations"] = 999
    traces["store_integrity_claim_mismatch"] = claim

    component = json.loads(json.dumps(trace))
    for event in component:
        if (
            event["kind"] == "release_component"
            and event["details"].get("component_id") == "SYNTH-CPI-CORE"
        ):
            event["details"]["component_id"] = "ABSENT-COMPONENT"
    traces["component_payload_mismatch"] = component

    spoof = json.loads(json.dumps(trace))
    for event in spoof:
        if event["kind"] == "run_started":
            event["details"]["provenance"] = "licensed_shadow"
    traces["synthetic_license_spoof"] = spoof

    results: dict[str, dict[str, Any]] = {}
    for name, value in traces.items():
        package = audit(value)
        target = expected[name]
        results[name] = {
            "passed": target in package["issues"] and package["enrollable"] is False,
            "expected_issue": target,
            "issues": package["issues"],
            "package_hash": package["package_hash"],
        }

    valid_package = audit(trace)
    duplicate = validate_ledger_candidates([valid_package, valid_package])
    target = expected["duplicate_ledger_record"]
    results["duplicate_ledger_record"] = {
        "passed": target in duplicate["issues"] and duplicate["passed"] is False,
        "expected_issue": target,
        "issues": duplicate["issues"],
    }
    return results


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    return f"""# Phase 5 result

Phase 5 evidence-enrollment pipeline is **{summary['pipeline_status']}**.
It made no authenticated request and enrolled no empirical window.

## Offline package

- capture observations: {summary['counts']['capture_observations']}
- immutable raw blobs: {summary['counts']['raw_blobs']}
- normalized snapshots: {summary['counts']['normalized_snapshots']}
- trace events: {summary['counts']['trace_events']}
- capture references: {summary['counts']['capture_references']}
- structurally complete: {summary['evidence_package']['structurally_complete']}
- enrollable: {summary['evidence_package']['enrollable']}

The synthetic package proves cross-link plumbing but is rejected by provenance,
schedule and rights gates. Its package hash is
`{summary['evidence_package']['package_hash']}`.

## External gate

- credential present: {summary['preflight']['credential_present']}
- rights attestation present: {summary['preflight']['rights_attestation_present']}
- empirical windows enrolled: {summary['counts']['empirical_windows_enrolled']}
- campaign promoted: {summary['campaign_checkpoint']['promoted']}

## Checks

{checks}

The final verifier checks preregistration, input hashes, deterministic replay and
the complete regression suite.
"""


def run_phase5(
    specification_path: Path,
    evidence_contract_path: Path,
    capture_contract_path: Path,
    campaign_contract_path: Path,
    schedule_path: Path,
    trace_path: Path,
    pre_payload_path: Path,
    post_payload_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    evidence_contract = json.loads(evidence_contract_path.read_text(encoding="utf-8"))
    capture_contract = json.loads(capture_contract_path.read_text(encoding="utf-8"))
    json.loads(campaign_contract_path.read_text(encoding="utf-8"))
    policy = specification["policy"]
    gates = specification["completion_gates"]

    plans = build_release_plans(schedule_path, policy)
    if len(plans) != 1:
        raise ValueError("registered Phase 5 drill requires exactly one plan")
    plan = plans[0]
    capture_store = VendorCaptureStore(output_dir / "capture_store")
    pre_capture_id, post_capture_id = _populate_synthetic_capture_store(
        capture_store, pre_payload_path, post_payload_path
    )
    fixture_trace = load_linked_trace_fixture(
        trace_path,
        plan,
        pre_capture_id=pre_capture_id,
        post_capture_id=post_capture_id,
    )
    trace_store = ShadowTraceStore(output_dir / "trace_store")
    stored_trace = trace_store.events()
    if not stored_trace:
        for event in fixture_trace:
            trace_store.append(event)
        stored_trace = trace_store.events()
    elif stored_trace != fixture_trace:
        raise RuntimeError(
            "existing Phase 5 trace differs from the registered fixture; preserve it"
        )

    credential = os.environ.get("TRADING_ECONOMICS_API_KEY", "")
    package = audit_evidence_package(
        plan,
        stored_trace,
        capture_store,
        policy,
        forbidden_values=(credential,) if credential else (),
    )
    replay_package = audit_evidence_package(
        plan,
        trace_store.events(),
        capture_store,
        policy,
        forbidden_values=(credential,) if credential else (),
    )
    failures = _run_failure_injections(
        plan,
        stored_trace,
        capture_store,
        policy,
        specification["failure_injections"],
    )
    preflight = vendor_access_preflight()
    checkpoint = campaign_checkpoint([], policy)
    observations = capture_store.observations()
    snapshots = capture_store.replay()
    integrity = capture_store.integrity_report(
        forbidden_values=(credential,) if credential else ()
    )
    counts = {
        "capture_observations": len(observations),
        "raw_blobs": integrity["unique_raw_blobs"],
        "normalized_snapshots": len(snapshots),
        "trace_events": len(stored_trace),
        "capture_references": package["capture_reference_count"],
        "empirical_windows_enrolled": checkpoint["eligible_packages"],
    }
    required_package = set(evidence_contract["required_package_fields"])
    required_observation = set(capture_contract["required_observation_fields"])
    checks = {
        "evidence_contract_schema_valid": required_package
        == set(EVIDENCE_PACKAGE_FIELDS)
        and required_observation == set(CAPTURE_OBSERVATION_FIELDS),
        "capture_observations": counts["capture_observations"]
        == gates["capture_observations"],
        "raw_blobs": counts["raw_blobs"] == gates["raw_blobs"],
        "normalized_snapshots": counts["normalized_snapshots"]
        == gates["normalized_snapshots"],
        "trace_events": counts["trace_events"] == gates["trace_events"],
        "capture_references": counts["capture_references"]
        == gates["capture_references"],
        "structurally_complete": package["structurally_complete"]
        is gates["structurally_complete"],
        "synthetic_not_enrollable": package["enrollable"]
        is gates["synthetic_enrollable"],
        "zero_empirical_enrollments": counts["empirical_windows_enrolled"]
        == gates["empirical_windows_enrolled"],
        "all_failure_injections_rejected": all(
            result["passed"] for result in failures.values()
        ),
        "deterministic_package_hash": package["package_hash"]
        == replay_package["package_hash"],
        "credential_absent": preflight["credential_present"]
        is gates["credential_present"],
        "rights_attestation_absent": preflight["rights_attestation_present"]
        is gates["rights_attestation_present"],
        "no_authenticated_vendor_request": gates[
            "authenticated_vendor_request_executed"
        ]
        is False,
        "no_market_price_join": gates["market_price_join_executed"] is False,
        "no_price_model": gates["price_model_executed"] is False,
    }
    passed = all(checks.values())
    summary = {
        "trial_id": specification["trial_id"],
        "phase5_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_FOR_LICENSED_EVIDENCE_ENROLLMENT_PENDING_VERIFICATION"
            if passed
            else "FAIL_EVIDENCE_ENROLLMENT"
        ),
        "external_status": specification["external_status"],
        "economic_decision": (
            "NO_GO_PRICE_EXPERIMENT_LICENSED_CAMPAIGN_REQUIRED"
        ),
        "counts": counts,
        "evidence_package": package,
        "replay_package_hash": replay_package["package_hash"],
        "capture_integrity": integrity,
        "failure_injections": failures,
        "preflight": preflight,
        "campaign_checkpoint": checkpoint,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
        "limitations": [
            "all offline inputs are original synthetic fixtures",
            "no paid credential or approved rights attestation was present",
            "zero scheduled licensed release windows were observed",
            "operational evidence does not establish predictive edge",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "capture_observations.json", observations)
    _write_json(output_dir / "normalized_snapshots.json", [asdict(item) for item in snapshots])
    _write_json(output_dir / "linked_trace.json", stored_trace)
    _write_json(output_dir / "evidence_package.json", package)
    _write_json(output_dir / "capture_integrity.json", integrity)
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "vendor_access_preflight.json", preflight)
    _write_json(output_dir / "campaign_checkpoint.json", checkpoint)
    _write_json(output_dir / "phase5_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "package_hash": package["package_hash"],
        },
    )
    (output_dir / "PHASE5_REPORT.md").write_text(_report(summary), encoding="utf-8")
    return summary
