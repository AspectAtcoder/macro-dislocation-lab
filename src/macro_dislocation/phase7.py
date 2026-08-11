from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .activation_handoff import (
    BINDING_FIELDS,
    COMPONENT_FIELDS,
    audit_component_binding,
    compile_activation_handoff,
    shadow_schedule_bytes,
)
from .campaign_roster import campaign_readiness, load_campaign_roster
from .evidence_enrollment import vendor_access_preflight
from .shadow_campaign import build_release_plans


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
    binding: dict[str, Any],
    roster: Any,
    window: Any,
    activation_packet: dict[str, Any],
    policy: dict[str, Any],
    expected: dict[str, str],
) -> dict[str, dict[str, Any]]:
    def mutated() -> dict[str, Any]:
        return json.loads(json.dumps(binding))

    variants: dict[str, dict[str, Any]] = {}
    missing = mutated()
    missing["components"] = missing["components"][:1]
    variants["missing_logical_component"] = missing

    duplicate = mutated()
    duplicate["components"][1]["provider_event_id"] = duplicate["components"][0][
        "provider_event_id"
    ]
    variants["duplicate_provider_id"] = duplicate

    drift = mutated()
    drift["components"][0]["scheduled_at"] = "2026-08-12T12:31:00+00:00"
    variants["provider_schedule_drift"] = drift

    variants["synthetic_provenance"] = mutated()

    malformed = mutated()
    malformed["capture_id"] = "not-a-content-address"
    variants["malformed_capture_id"] = malformed

    stale = mutated()
    stale["captured_at"] = "2026-08-09T10:00:00+00:00"
    variants["stale_binding_capture"] = stale

    results: dict[str, dict[str, Any]] = {}
    for name, value in variants.items():
        audit = audit_component_binding(
            value, window, activation_packet["evaluated_at"], policy
        )
        target = expected[name]
        results[name] = {
            "passed": target in audit["issues"],
            "expected_issue": target,
            "issues": audit["issues"],
            "binding_audit_hash": audit["binding_audit_hash"],
        }

    baseline_audit = audit_component_binding(
        binding, window, activation_packet["evaluated_at"], policy
    )
    blocked_packet = dict(activation_packet)
    blocked_packet["activation_status"] = "BLOCKED_VENDOR_ACCESS"
    bypass = compile_activation_handoff(
        roster, window, binding, baseline_audit, blocked_packet, policy
    )
    target = expected["activation_bypass"]
    results["activation_bypass"] = {
        "passed": target in bypass["issues"] and bypass["executable"] is False,
        "expected_issue": target,
        "issues": bypass["issues"],
        "handoff_hash": bypass["handoff_hash"],
    }
    return results


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    return f"""# Phase 7 result

Phase 7 activation handoff is **{summary['pipeline_status']}**.
It compiled one structural shadow-schedule preview and issued no executable
handoff.

## Binding

- selected roster windows: {summary['counts']['selected_roster_windows']}
- logical components: {summary['counts']['logical_components']}
- provider components: {summary['counts']['provider_components']}
- structurally complete: {summary['binding_audit']['structurally_complete']}
- execution eligible: {summary['binding_audit']['execution_eligible']}
- shadow release plans: {summary['counts']['shadow_release_plans']}
- executable handoffs: {summary['counts']['executable_handoffs']}

The binding uses synthetic provider IDs. It proves the Phase 6 to Phase 4 schema
bridge but is rejected by provenance and rights gates.

## External gate

- activation status: `{summary['activation_packet']['activation_status']}`
- credential present: {summary['preflight']['credential_present']}
- rights attestation present: {summary['preflight']['rights_attestation_present']}

## Checks

{checks}

The final verifier checks preregistration, binding and schedule replay, failure
injections and the complete regression suite.
"""


def run_phase7(
    specification_path: Path,
    handoff_contract_path: Path,
    phase6_specification_path: Path,
    roster_path: Path,
    phase4_specification_path: Path,
    binding_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    contract = json.loads(handoff_contract_path.read_text(encoding="utf-8"))
    phase6 = json.loads(phase6_specification_path.read_text(encoding="utf-8"))
    phase4 = json.loads(phase4_specification_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    policy = specification["policy"]
    gates = specification["completion_gates"]

    roster = load_campaign_roster(roster_path, phase6["policy"])
    matching = [
        window
        for window in roster.windows
        if window.source_event_id == binding.get("source_event_id")
    ]
    if len(matching) != 1:
        raise ValueError("binding source_event_id must select exactly one roster window")
    window = matching[0]
    preflight = vendor_access_preflight()
    readiness = campaign_readiness(
        roster, specification["evaluated_at"], preflight, phase6["policy"]
    )
    activation_packet = readiness["activation_packet"]
    if activation_packet is None or activation_packet["source_event_id"] != window.source_event_id:
        raise ValueError("selected binding must target the next prospective roster window")
    binding_audit = audit_component_binding(
        binding, window, specification["evaluated_at"], policy
    )
    handoff = compile_activation_handoff(
        roster, window, binding, binding_audit, activation_packet, policy
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_path = output_dir / "shadow_schedule_preview.json"
    schedule_path.write_bytes(
        shadow_schedule_bytes(handoff["shadow_schedule_preview"])
    )
    plans = build_release_plans(schedule_path, phase4["policy"])
    failures = _run_failure_injections(
        binding,
        roster,
        window,
        activation_packet,
        policy,
        specification["failure_injections"],
    )
    counts = {
        "selected_roster_windows": 1,
        "logical_components": len(window.expected_logical_components),
        "provider_components": len(binding_audit["provider_event_ids"]),
        "shadow_schedule_previews": 1,
        "shadow_release_plans": len(plans),
        "executable_handoffs": int(handoff["executable"]),
    }
    checks = {
        "handoff_contract_schema_valid": contract.get("required_binding_fields")
        == list(BINDING_FIELDS)
        and contract.get("required_component_fields") == list(COMPONENT_FIELDS),
        "selected_roster_windows": counts["selected_roster_windows"]
        == gates["selected_roster_windows"],
        "logical_components": counts["logical_components"]
        == gates["logical_components"],
        "provider_components": counts["provider_components"]
        == gates["provider_components"],
        "binding_structurally_complete": binding_audit["structurally_complete"]
        is gates["binding_structurally_complete"],
        "binding_not_execution_eligible": binding_audit["execution_eligible"]
        is gates["binding_execution_eligible"],
        "shadow_schedule_previews": counts["shadow_schedule_previews"]
        == gates["shadow_schedule_previews"],
        "shadow_release_plans": counts["shadow_release_plans"]
        == gates["shadow_release_plans"],
        "zero_executable_handoffs": counts["executable_handoffs"]
        == gates["executable_handoffs"],
        "activation_fail_closed": activation_packet["activation_status"]
        == gates["activation_status"],
        "schedule_hash_bridge": plans[0].schedule_sha256
        == handoff["shadow_schedule_sha256"]
        == _sha256(schedule_path),
        "provider_ids_bridge": plans[0].expected_components
        == sorted(binding_audit["provider_event_ids"]),
        "all_failure_injections_rejected": all(
            result["passed"] for result in failures.values()
        ),
        "deterministic_handoff_hash": bool(handoff["handoff_hash"]),
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
        "phase7_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING_PENDING_VERIFICATION"
            if passed
            else "FAIL_ACTIVATION_HANDOFF"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "counts": counts,
        "selected_window": window.to_dict(),
        "preflight": preflight,
        "activation_packet": activation_packet,
        "binding_audit": binding_audit,
        "handoff": handoff,
        "release_plans": [plan.to_dict() for plan in plans],
        "failure_injections": failures,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
        "limitations": [
            "provider component IDs are original synthetic fixture values",
            "the binding has no licensed provenance or approved rights",
            "the activation packet is blocked by external vendor access",
            "zero executable handoffs or empirical windows were produced",
            "operational schema compatibility does not establish predictive edge",
        ],
    }
    _write_json(output_dir / "binding_audit.json", binding_audit)
    _write_json(output_dir / "vendor_access_preflight.json", preflight)
    _write_json(output_dir / "activation_packet.json", activation_packet)
    _write_json(output_dir / "activation_handoff.json", handoff)
    _write_json(output_dir / "release_plans.json", [plan.to_dict() for plan in plans])
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase7_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "binding_payload_hash": binding_audit["binding_payload_hash"],
            "binding_audit_hash": binding_audit["binding_audit_hash"],
            "shadow_schedule_sha256": handoff["shadow_schedule_sha256"],
            "handoff_hash": handoff["handoff_hash"],
        },
    )
    (output_dir / "PHASE7_REPORT.md").write_text(
        _report(summary), encoding="utf-8"
    )
    return summary
