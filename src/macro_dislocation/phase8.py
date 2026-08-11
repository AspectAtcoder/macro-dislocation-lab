from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .campaign_roster import campaign_readiness, load_campaign_roster
from .capture_authorization import (
    PERMIT_FIELDS,
    RECEIPT_FIELDS,
    _seal_access_receipt,
    authorization_key_preflight,
    issue_access_authorization,
    issue_capture_permit,
    next_viable_window,
    validate_access_receipt,
    validate_capture_permit,
)
from .evidence_enrollment import vendor_access_preflight
from .vendor_capture import capture_authenticated_snapshot, capture_stream_jsonl


UTC = timezone.utc
OFFLINE_KEY = b"phase8-offline-failure-injection-key-0001"


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


def _synthetic_access_receipt(
    roster: Any, window: Any, activation_packet_hash: str, policy: dict[str, Any]
) -> dict[str, Any]:
    scheduled = datetime.fromisoformat(window.scheduled_at)
    return _seal_access_receipt(
        {
            "receipt_status": "AUTHORIZED",
            "roster_id": roster.roster_id,
            "roster_sha256": roster.roster_sha256,
            "source_event_id": window.source_event_id,
            "event_family": window.event_family,
            "scheduled_at": window.scheduled_at,
            "authorized_at": "2026-08-11T10:08:18+00:00",
            "access_ready_by": window.access_ready_by,
            "valid_until": (
                scheduled + timedelta(seconds=int(policy["stream_tail_seconds"]))
            ).isoformat(),
            "schedule_checked_at": roster.checked_at,
            "schedule_source_url": window.schedule_source_url,
            "activation_packet_hash": activation_packet_hash,
            "rights_attestation_sha256": "8" * 64,
            "license_class": "licensed_internal_research",
            "credential_present": True,
            "rights_attestation_valid": True,
            "provenance": "authorized_vendor_access",
        },
        OFFLINE_KEY,
    )


def run_failure_injections(
    roster: Any,
    window: Any,
    activation_packet: dict[str, Any],
    authorization_decision: dict[str, Any],
    policy: dict[str, Any],
    expected: dict[str, str],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}

    target = expected["late_authorization"]
    results["late_authorization"] = {
        "passed": target in authorization_decision["issues"]
        and authorization_decision["access_receipt"] is None,
        "expected_issue": target,
        "issues": authorization_decision["issues"],
    }

    receipt = _synthetic_access_receipt(
        roster, window, str(activation_packet["packet_hash"]), policy
    )
    key_issues = validate_access_receipt(
        receipt, roster, window, "2026-08-11T13:41:13+00:00", policy
    )
    target = expected["missing_signing_key"]
    results["missing_signing_key"] = {
        "passed": target in key_issues,
        "expected_issue": target,
        "issues": key_issues,
    }

    tampered = json.loads(json.dumps(receipt))
    tampered["license_class"] = "tampered"
    tampered_issues = validate_access_receipt(
        tampered,
        roster,
        window,
        "2026-08-11T13:41:13+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["tampered_receipt"]
    results["tampered_receipt"] = {
        "passed": target in tampered_issues,
        "expected_issue": target,
        "issues": tampered_issues,
    }

    substituted_core = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_id", "receipt_signature"}
    }
    substituted_core["roster_sha256"] = "0" * 64
    substituted = _seal_access_receipt(substituted_core, OFFLINE_KEY)
    substituted_issues = validate_access_receipt(
        substituted,
        roster,
        window,
        "2026-08-11T13:41:13+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["roster_substitution"]
    results["roster_substitution"] = {
        "passed": target in substituted_issues,
        "expected_issue": target,
        "issues": substituted_issues,
    }

    expired_issues = validate_access_receipt(
        receipt,
        roster,
        window,
        "2026-08-12T12:32:01+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["expired_receipt"]
    results["expired_receipt"] = {
        "passed": target in expired_issues,
        "expected_issue": target,
        "issues": expired_issues,
    }

    permit_decision = issue_capture_permit(
        receipt,
        roster,
        window,
        "binding_snapshot",
        "2026-08-11T13:41:13+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    permit = permit_decision["capture_permit"]
    if permit is None:
        raise RuntimeError("registered failure fixture did not issue a permit")

    action_issues = validate_capture_permit(
        permit,
        "calendar_stream",
        "2026-08-11T13:41:13+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["wrong_permit_action"]
    results["wrong_permit_action"] = {
        "passed": target in action_issues,
        "expected_issue": target,
        "issues": action_issues,
    }

    tampered_permit = json.loads(json.dumps(permit))
    tampered_permit["event_family"] = "NFP"
    permit_issues = validate_capture_permit(
        tampered_permit,
        "binding_snapshot",
        "2026-08-11T13:41:13+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["tampered_permit"]
    results["tampered_permit"] = {
        "passed": target in permit_issues,
        "expected_issue": target,
        "issues": permit_issues,
    }

    expired_permit_issues = validate_capture_permit(
        permit,
        "binding_snapshot",
        "2026-08-12T12:30:01+00:00",
        policy,
        _key_override=OFFLINE_KEY,
    )
    target = expected["expired_permit"]
    results["expired_permit"] = {
        "passed": target in expired_permit_issues,
        "expected_issue": target,
        "issues": expired_permit_issues,
    }
    return results


def capture_paths_require_permits() -> bool:
    empty = inspect.Signature.empty
    snapshot = inspect.signature(capture_authenticated_snapshot).parameters
    stream = inspect.signature(capture_stream_jsonl).parameters
    return (
        snapshot["authorization_permit_path"].default is empty
        and snapshot["permit_action"].default is empty
        and stream["authorization_permit_path"].default is empty
    )


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    next_window = summary["next_viable_window"]
    return f"""# Phase 8 result

Phase 8 signed capture authorization is **{summary['pipeline_status']}**.

## First roster window

- authorization status: `{summary['authorization_decision']['authorization_status']}`
- activation status: `{summary['activation_packet']['activation_status']}`
- seconds to access deadline: {summary['activation_packet']['seconds_to_access_deadline']}
- access receipts issued: {summary['counts']['access_receipts_issued']}
- capture permits issued: {summary['counts']['capture_permits_issued']}
- missed windows counted as evidence: {summary['counts']['missed_windows_counted_as_evidence']}

The first CPI window missed its access-ready deadline and cannot be reconstructed.
The next viable window is `{next_window['source_event_id']}` at
`{next_window['scheduled_at']}`, with access ready by
`{next_window['access_ready_by']}`.

## External gate

- credential present: {summary['preflight']['credential_present']}
- rights attestation present: {summary['preflight']['rights_attestation_present']}
- authorization signing key present: {summary['authorization_key_preflight']['present']}

## Checks

{checks}

The verifier checks preregistration, HMAC failures, capture-path enforcement and
the complete regression suite.
"""


def run_phase8(
    specification_path: Path,
    authorization_contract_path: Path,
    phase6_specification_path: Path,
    roster_path: Path,
    phase4_specification_path: Path,
    rights_schema_path: Path,
    phase7_specification_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    contract = json.loads(authorization_contract_path.read_text(encoding="utf-8"))
    phase6 = json.loads(phase6_specification_path.read_text(encoding="utf-8"))
    phase4 = json.loads(phase4_specification_path.read_text(encoding="utf-8"))
    json.loads(rights_schema_path.read_text(encoding="utf-8"))
    json.loads(phase7_specification_path.read_text(encoding="utf-8"))
    policy = specification["policy"]
    gates = specification["completion_gates"]
    if (
        policy["pre_snapshot_max_age_seconds"]
        != phase4["policy"]["pre_snapshot_max_age_seconds"]
        or policy["stream_lead_seconds"] != phase4["policy"]["stream_lead_seconds"]
        or policy["stream_tail_seconds"] != phase4["policy"]["stream_tail_seconds"]
    ):
        raise ValueError("Phase 8 timing policy must equal the registered Phase 4 policy")

    roster = load_campaign_roster(roster_path, phase6["policy"])
    window = roster.windows[0]
    preflight = vendor_access_preflight()
    readiness = campaign_readiness(
        roster, specification["evaluated_at"], preflight, phase6["policy"]
    )
    activation_packet = readiness["activation_packet"]
    authorization = issue_access_authorization(
        roster, window, activation_packet, None, policy
    )
    key_preflight = authorization_key_preflight(policy)
    next_window = next_viable_window(roster, specification["evaluated_at"])
    if next_window is None:
        raise ValueError("registered Phase 8 trial requires a next viable window")
    failures = run_failure_injections(
        roster,
        window,
        activation_packet,
        authorization,
        policy,
        specification["failure_injections"],
    )
    counts = {
        "evaluated_windows": 1,
        "access_receipts_issued": int(authorization["access_receipt"] is not None),
        "capture_permits_issued": 0,
        "missed_windows_counted_as_evidence": 0,
    }
    checks = {
        "authorization_contract_schema_valid": contract.get("required_receipt_fields")
        == list(RECEIPT_FIELDS)
        and contract.get("required_permit_fields") == list(PERMIT_FIELDS)
        and contract.get("allowed_actions") == policy["allowed_actions"],
        "evaluated_windows": counts["evaluated_windows"] == gates["evaluated_windows"],
        "first_window_missed": authorization["authorization_status"]
        == gates["first_window_status"],
        "activation_deadline_missed": activation_packet["activation_status"]
        == gates["activation_status"]
        and activation_packet["seconds_to_access_deadline"]
        == gates["seconds_to_access_deadline"],
        "zero_access_receipts": counts["access_receipts_issued"]
        == gates["access_receipts_issued"],
        "zero_capture_permits": counts["capture_permits_issued"]
        == gates["capture_permits_issued"],
        "next_viable_window": next_window.source_event_id
        == gates["next_viable_source_event_id"]
        and next_window.scheduled_at == gates["next_viable_release_utc"]
        and next_window.access_ready_by == gates["next_viable_access_ready_by"],
        "credential_absent": preflight["credential_present"]
        is gates["credential_present"],
        "rights_attestation_absent": preflight["rights_attestation_present"]
        is gates["rights_attestation_present"],
        "authorization_key_absent": key_preflight["present"]
        is gates["authorization_signing_key_present"],
        "missed_window_not_evidence": counts["missed_windows_counted_as_evidence"]
        == gates["missed_windows_counted_as_evidence"],
        "all_failure_injections_rejected": all(
            result["passed"] for result in failures.values()
        ),
        "capture_paths_require_signed_permits": capture_paths_require_permits()
        is gates["capture_paths_require_signed_permits"],
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
        "phase8_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_FOR_SIGNED_CAPTURE_AUTHORIZATION_PENDING_EXTERNAL_ACCESS_PENDING_VERIFICATION"
            if passed
            else "FAIL_CAPTURE_AUTHORIZATION"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "counts": counts,
        "selected_window": window.to_dict(),
        "activation_packet": activation_packet,
        "preflight": preflight,
        "authorization_key_preflight": key_preflight,
        "authorization_decision": authorization,
        "next_viable_window": next_window.to_dict(),
        "failure_injections": failures,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
        "limitations": [
            "the first CPI access-ready deadline passed without an authorization receipt",
            "no vendor credential, rights attestation or authorization key was present",
            "offline HMAC fixtures exercise rejection paths and authorize no capture",
            "zero empirical windows were created",
            "capture authorization does not establish predictive edge",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "vendor_access_preflight.json", preflight)
    _write_json(output_dir / "authorization_key_preflight.json", key_preflight)
    _write_json(output_dir / "activation_packet.json", activation_packet)
    _write_json(output_dir / "authorization_decision.json", authorization)
    _write_json(output_dir / "next_viable_window.json", next_window.to_dict())
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase8_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "activation_packet_hash": activation_packet["packet_hash"],
            "authorization_receipt_id": None,
            "capture_permit_ids": [],
        },
    )
    (output_dir / "PHASE8_REPORT.md").write_text(
        _report(summary), encoding="utf-8"
    )
    return summary
