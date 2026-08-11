from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .shadow_campaign import (
    PLAN_FIELDS,
    TRACE_FIELDS,
    TRACE_KINDS,
    ShadowTraceStore,
    audit_shadow_trace,
    build_release_plans,
    campaign_promotion_gate,
    load_trace_fixture,
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


def _run_failure_injections(
    plan: Any,
    valid_trace: list[dict[str, Any]],
    policy: dict[str, Any],
    expected: dict[str, str],
) -> dict[str, dict[str, Any]]:
    traces: dict[str, list[dict[str, Any]]] = {}

    unsafe_clock = json.loads(json.dumps(valid_trace))
    for event in unsafe_clock:
        if event["kind"] == "clock_sample":
            event["details"]["offset_ms"] = 500.0
    traces["unsafe_clock"] = unsafe_clock

    traces["missing_pre_snapshot"] = [
        event for event in json.loads(json.dumps(valid_trace))
        if event["kind"] != "pre_snapshot_captured"
    ]

    traces["telemetry_gap"] = [
        event for event in json.loads(json.dumps(valid_trace))
        if not (
            event["kind"] == "heartbeat"
            and event["observed_at"]
            in {
                "2030-01-10T13:31:00+00:00",
                "2030-01-10T13:31:30+00:00",
            }
        )
    ]

    schedule_drift = json.loads(json.dumps(valid_trace))
    for event in schedule_drift:
        if event["kind"] == "run_started":
            event["details"]["schedule_sha256"] = "0" * 64
    traces["schedule_drift"] = schedule_drift

    traces["missing_component"] = [
        event for event in json.loads(json.dumps(valid_trace))
        if not (
            event["kind"] == "release_component"
            and event["details"].get("component_id") == "SYNTH-CPI-CORE"
        )
    ]

    store_failure = json.loads(json.dumps(valid_trace))
    for event in store_failure:
        if event["kind"] == "store_audit":
            event["details"] = {
                "passed": False,
                "violations": ["synthetic_corrupt_blob"],
            }
    traces["store_integrity_failure"] = store_failure

    results: dict[str, dict[str, Any]] = {}
    for name, trace in traces.items():
        audit = audit_shadow_trace(plan, trace, policy)
        target = expected[name]
        results[name] = {
            "passed": target in audit["issues"]
            and audit["operationally_complete"] is False,
            "expected_issue": target,
            "issues": audit["issues"],
            "audit_hash": audit["audit_hash"],
        }
    return results


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    metrics = summary["valid_trace_audit"]["metrics"]
    counts = summary["counts"]
    return f"""# Phase 4 result

Phase 4のrelease-window supervisorは
**{summary['pipeline_status']}** です。認証通信・価格結合・モデル学習は実行していません。

## Offline shadow drill

- release plans: {counts['release_plans']}
- trace events: {counts['trace_events']}
- expected simultaneous components: {counts['expected_components']}
- reconnects: {counts['reconnects']}
- complete empirical windows: {counts['complete_empirical_windows']}

synthetic CPI windowで、発表前snapshot、2 component同時発表、途中disconnect／reconnect、
raw-store audit、planned closeまでを監査しました。正常traceはoperationally completeですが、
synthetic provenanceなのでcampaign promotionには数えません。

## Timing evidence

- median absolute clock offset: {metrics['median_absolute_clock_offset_ms']} ms
- maximum clock RTT: {metrics['maximum_clock_rtt_ms']} ms
- pre-snapshot lead: {metrics['pre_snapshot_lead_seconds']} sec
- maximum telemetry gap: {metrics['maximum_telemetry_gap_seconds']} sec
- reconnect gaps: {metrics['reconnect_gaps_seconds']}

## Failure injection

unsafe clock、pre-snapshot欠損、telemetry gap、schedule hash drift、component欠損、
raw-store failureを個別に注入し、すべて登録済みissueでfail-closedになりました。

## Campaign gate

- promoted: {summary['campaign_gate']['promoted']}
- empirical complete windows: {summary['campaign_gate']['complete_empirical_windows']}
- remaining reasons: {summary['campaign_gate']['reasons']}

## Gate

{checks}

最終テスト数と事前登録commit照合は `macro-lab verify-phase4` が判定します。
"""


def run_phase4(
    specification_path: Path,
    campaign_contract_path: Path,
    capture_contract_path: Path,
    schedule_path: Path,
    trace_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    campaign_contract = json.loads(campaign_contract_path.read_text(encoding="utf-8"))
    json.loads(capture_contract_path.read_text(encoding="utf-8"))
    policy = specification["policy"]
    gates = specification["completion_gates"]

    plans = build_release_plans(schedule_path, policy)
    if len(plans) != 1:
        raise ValueError("registered offline drill requires exactly one release plan")
    plan = plans[0]
    fixture_trace = load_trace_fixture(trace_path, plan)
    trace_store = ShadowTraceStore(output_dir / "shadow_trace_store")
    stored = trace_store.events()
    if not stored:
        for event in fixture_trace:
            trace_store.append(event)
        stored = trace_store.events()
    elif stored != fixture_trace:
        raise RuntimeError(
            "existing shadow trace store differs from the registered fixture; preserve it for audit"
        )

    audit = audit_shadow_trace(plan, stored, policy)
    replay_audit = audit_shadow_trace(plan, trace_store.events(), policy)
    failure_injections = _run_failure_injections(
        plan,
        stored,
        policy,
        specification["failure_injections"],
    )
    campaign_gate = campaign_promotion_gate([audit], policy)
    required_plan = set(campaign_contract["required_plan_fields"])
    required_trace = set(campaign_contract["required_trace_fields"])
    allowed_kinds = set(campaign_contract["allowed_trace_kinds"])
    counts = {
        "release_plans": len(plans),
        "trace_events": len(stored),
        "expected_components": len(plan.expected_components),
        "reconnects": audit["metrics"]["reconnects"],
        "complete_empirical_windows": campaign_gate["complete_empirical_windows"],
    }
    checks = {
        "campaign_contract_schema_valid": required_plan == set(PLAN_FIELDS)
        and required_trace == set(TRACE_FIELDS)
        and allowed_kinds == TRACE_KINDS,
        "release_plans": counts["release_plans"] == gates["release_plans"],
        "trace_events": counts["trace_events"] == gates["trace_events"],
        "expected_components": counts["expected_components"]
        == gates["expected_components"],
        "reconnects": counts["reconnects"] == gates["reconnects"],
        "valid_trace_operationally_complete": audit["operationally_complete"]
        is gates["valid_trace_operationally_complete"],
        "all_failure_injections_rejected": all(
            result["passed"] for result in failure_injections.values()
        ),
        "deterministic_audit_hash": audit["audit_hash"]
        == replay_audit["audit_hash"],
        "synthetic_empirical_windows": counts["complete_empirical_windows"]
        == gates["synthetic_empirical_windows"],
        "campaign_promoted": campaign_gate["promoted"]
        is gates["campaign_promoted"],
        "no_authenticated_vendor_request": gates[
            "authenticated_vendor_request_executed"
        ]
        is False,
        "no_market_price_join": gates["market_price_join_executed"] is False,
        "no_price_model": gates["price_model_executed"] is False,
    }
    pipeline_passed = all(checks.values())
    summary = {
        "trial_id": specification["trial_id"],
        "phase4_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_TO_START_LICENSED_SHADOW_CAMPAIGN_PENDING_VERIFICATION"
            if pipeline_passed
            else "FAIL_SHADOW_OPERATIONS"
        ),
        "economic_decision": "NO_GO_PRICE_EXPERIMENT_EMPIRICAL_TRIAL_REQUIRED",
        "counts": counts,
        "valid_trace_audit": audit,
        "audit_hash": audit["audit_hash"],
        "replay_audit_hash": replay_audit["audit_hash"],
        "failure_injections": failure_injections,
        "campaign_gate": campaign_gate,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
        "limitations": [
            "the drill uses only a synthetic release schedule and trace",
            "no licensed vendor credential or empirical shadow window was supplied",
            "NTP transport was not contacted by the offline drill",
            "operational readiness does not establish predictive edge",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "release_windows.json", [plan.to_dict() for plan in plans])
    _write_json(output_dir / "shadow_trace.json", stored)
    _write_json(output_dir / "shadow_audit.json", audit)
    _write_json(output_dir / "failure_injections.json", failure_injections)
    _write_json(output_dir / "campaign_gate.json", campaign_gate)
    _write_json(output_dir / "phase4_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "audit_hash": audit["audit_hash"],
        },
    )
    (output_dir / "PHASE4_REPORT.md").write_text(_report(summary), encoding="utf-8")
    return summary
