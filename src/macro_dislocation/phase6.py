from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .campaign_roster import (
    ROSTER_EVENT_FIELDS,
    ROSTER_FIELDS,
    activation_packet,
    audit_roster_payload,
    campaign_readiness,
    load_campaign_roster,
)
from .evidence_enrollment import vendor_access_preflight


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
    roster_payload: dict[str, Any],
    roster: Any,
    preflight: dict[str, Any],
    policy: dict[str, Any],
    expected: dict[str, str],
) -> dict[str, dict[str, Any]]:
    def mutated() -> dict[str, Any]:
        return json.loads(json.dumps(roster_payload))

    audits: dict[str, dict[str, Any]] = {}
    fixed = mutated()
    fixed["official_timezone"] = "Etc/GMT+4"
    audits["fixed_offset_dst"] = audit_roster_payload(fixed, policy)

    duplicate = mutated()
    duplicate["events"].append(dict(duplicate["events"][0]))
    audits["duplicate_release"] = audit_roster_payload(duplicate, policy)

    missing = mutated()
    missing["events"] = [
        item for item in missing["events"] if item["event_family"] != "CPI"
    ]
    audits["missing_cpi_floor"] = audit_roster_payload(missing, policy)

    insecure = mutated()
    insecure["sources"]["CPI"] = "http://example.invalid/cpi.htm"
    audits["insecure_source"] = audit_roster_payload(insecure, policy)

    results: dict[str, dict[str, Any]] = {}
    for name, audit in audits.items():
        target = expected[name]
        results[name] = {
            "passed": audit["passed"] is False and target in audit["issues"],
            "expected_issue": target,
            "issues": audit["issues"],
            "audit_hash": audit["audit_hash"],
        }

    first = roster.windows[0]
    stale = replace(roster, checked_at="2026-08-01T00:00:00+00:00")
    stale_packet = activation_packet(
        stale, first, "2026-08-11T10:08:18+00:00", preflight, policy
    )
    target = expected["stale_activation_schedule"]
    results["stale_activation_schedule"] = {
        "passed": target in stale_packet["issues"],
        "expected_issue": target,
        "issues": stale_packet["issues"],
        "packet_hash": stale_packet["packet_hash"],
    }

    expired_packet = activation_packet(
        roster, first, "2026-08-12T12:30:01+00:00", preflight, policy
    )
    target = expected["activation_after_release"]
    results["activation_after_release"] = {
        "passed": target in expired_packet["issues"],
        "expected_issue": target,
        "issues": expired_packet["issues"],
        "packet_hash": expired_packet["packet_hash"],
    }
    return results


def _report(summary: dict[str, Any]) -> str:
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'}: `{name}`"
        for name, passed in summary["pipeline_checks"].items()
    )
    packet = summary["campaign_readiness"]["activation_packet"]
    return f"""# Phase 6 result

Phase 6 campaign roster is **{summary['pipeline_status']}**.
It scheduled operations but made no authenticated request and captured no
empirical window.

## Prospective roster

- campaign windows: {summary['counts']['campaign_windows']}
- CPI windows: {summary['counts']['cpi_windows']}
- Employment Situation windows: {summary['counts']['nfp_windows']}
- activation candidates at the frozen evaluation time: {summary['counts']['activation_candidates']}
- next release UTC: `{packet['scheduled_at']}`
- next release JST: `{packet['operator_at']}`
- access-ready deadline UTC: `{packet['access_ready_by']}`
- activation status: `{packet['activation_status']}`

The November Employment Situation conversion is
`{summary['november_nfp']['scheduled_at']}` UTC /
`{summary['november_nfp']['operator_at']}` JST, after the U.S. daylight-saving
transition.

## External gate

- credential present: {summary['preflight']['credential_present']}
- rights attestation present: {summary['preflight']['rights_attestation_present']}
- empirical windows captured: {summary['counts']['empirical_windows_captured']}

Missing a blocked release creates no evidence and cannot be backfilled as a live
receipt. Every later roster entry requires a new official schedule check.

## Checks

{checks}

The final verifier checks preregistration, roster replay, failure injections and
the complete regression suite.
"""


def run_phase6(
    specification_path: Path,
    roster_contract_path: Path,
    roster_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
    rights_attestation_path: Path | None = None,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    contract = json.loads(roster_contract_path.read_text(encoding="utf-8"))
    roster_payload = json.loads(roster_path.read_text(encoding="utf-8"))
    policy = specification["policy"]
    gates = specification["completion_gates"]

    audit = audit_roster_payload(roster_payload, policy)
    roster = load_campaign_roster(roster_path, policy)
    preflight = vendor_access_preflight(rights_attestation_path)
    readiness = campaign_readiness(
        roster, specification["evaluated_at"], preflight, policy
    )
    packet = readiness["activation_packet"]
    failures = _run_failure_injections(
        roster_payload,
        roster,
        preflight,
        policy,
        specification["failure_injections"],
    )
    november = next(
        window
        for window in roster.windows
        if window.source_event_id == "BLS-NFP-2026-10"
    )
    counts = {
        "campaign_windows": len(roster.windows),
        "cpi_windows": sum(w.event_family == "CPI" for w in roster.windows),
        "nfp_windows": sum(w.event_family == "NFP" for w in roster.windows),
        "activation_candidates": readiness["activation_candidates"],
        "empirical_windows_captured": 0,
    }
    checks = {
        "roster_contract_schema_valid": contract.get("required_roster_fields")
        == list(ROSTER_FIELDS)
        and contract.get("required_event_fields") == list(ROSTER_EVENT_FIELDS),
        "roster_audit_pass": audit["passed"] is True,
        "campaign_windows": counts["campaign_windows"]
        == gates["campaign_windows"],
        "cpi_windows": counts["cpi_windows"] == gates["cpi_windows"],
        "nfp_windows": counts["nfp_windows"] == gates["nfp_windows"],
        "activation_candidates": counts["activation_candidates"]
        == gates["activation_candidates"],
        "next_event_family": packet["event_family"] == gates["next_event_family"],
        "next_release_utc": packet["scheduled_at"] == gates["next_release_utc"],
        "next_release_jst": packet["operator_at"] == gates["next_release_jst"],
        "november_dst_conversion": november.scheduled_at
        == gates["november_nfp_utc"],
        "access_deadline": packet["seconds_to_access_deadline"]
        == gates["seconds_to_access_deadline"],
        "schedule_fresh": packet["schedule_fresh"]
        is gates["schedule_fresh_for_next_window"],
        "activation_fail_closed": packet["activation_status"]
        == gates["activation_status"],
        "credential_absent": preflight["credential_present"]
        is gates["credential_present"],
        "rights_attestation_absent": preflight["rights_attestation_present"]
        is gates["rights_attestation_present"],
        "zero_empirical_windows": counts["empirical_windows_captured"]
        == gates["empirical_windows_captured"],
        "all_failure_injections_rejected": all(
            result["passed"] for result in failures.values()
        ),
        "deterministic_roster_hash": roster.roster_sha256 == _sha256(roster_path),
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
        "phase6_status": "PIPELINE_EXECUTED",
        "pipeline_status": (
            "READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS_PENDING_VERIFICATION"
            if passed
            else "FAIL_CAMPAIGN_ROSTER"
        ),
        "external_status": specification["external_status"],
        "economic_decision": specification["economic_decision"],
        "counts": counts,
        "roster": roster.to_dict(),
        "roster_audit": audit,
        "campaign_readiness": readiness,
        "november_nfp": november.to_dict(),
        "failure_injections": failures,
        "preflight": preflight,
        "pipeline_checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
        "limitations": [
            "the roster is an operational schedule, not empirical evidence",
            "no paid credential or approved rights attestation was present",
            "official schedules can change and must be refreshed before activation",
            "zero licensed release windows were captured",
            "operational readiness does not establish predictive edge",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "normalized_roster.json", roster.to_dict())
    _write_json(output_dir / "roster_audit.json", audit)
    _write_json(output_dir / "vendor_access_preflight.json", preflight)
    _write_json(output_dir / "campaign_readiness.json", readiness)
    _write_json(output_dir / "activation_packet.json", packet)
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase6_summary.json", summary)
    inputs = {
        raw_path: _sha256(project_root / raw_path)
        for raw_path in specification["inputs"].values()
    }
    _write_json(
        output_dir / "manifest.json",
        {
            "trial_id": specification["trial_id"],
            "inputs": inputs,
            "roster_sha256": roster.roster_sha256,
            "readiness_hash": readiness["readiness_hash"],
            "packet_hash": packet["packet_hash"],
        },
    )
    (output_dir / "PHASE6_REPORT.md").write_text(
        _report(summary), encoding="utf-8"
    )
    return summary
