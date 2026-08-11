from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .campaign_state import CampaignJournal, replay_campaign, seal_campaign_event
from .verification_utils import manifest_key, sha256_path


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fixture_events(specification: dict[str, Any]) -> list[dict[str, Any]]:
    times = [
        "2031-01-10T12:00:00+00:00",
        "2031-01-10T12:05:00+00:00",
        "2031-01-10T12:10:00+00:00",
        "2031-01-10T13:27:00+00:00",
        "2031-01-10T13:32:00+00:00",
        "2031-01-10T13:35:00+00:00",
    ]
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, (state, occurred) in enumerate(
        zip(specification["state_order"], times), start=1
    ):
        event = seal_campaign_event(
            {
                "sequence": sequence,
                "campaign_id": "campaign:synthetic-phase9-001",
                "source_event_id": "SYNTH-CPI-2031-01",
                "state": state,
                "occurred_at": occurred,
                "evidence_id": None if state == "PLANNED" else f"evidence:{sequence}",
                "provenance": "synthetic_fixture",
                "previous_hash": previous,
            }
        )
        events.append(event)
        previous = event["event_hash"]
    return events


def failure_injections(
    events: list[dict[str, Any]], specification: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    expected = specification["failure_injections"]
    cases: dict[str, list[dict[str, Any]]] = {}

    out_of_order = json.loads(json.dumps(events[:2]))
    out_of_order[1]["state"] = "PRE_RELEASE_CAPTURED"
    out_of_order[1] = seal_campaign_event(out_of_order[1])
    cases["out_of_order_transition"] = out_of_order

    duplicate = json.loads(json.dumps(events[:2]))
    duplicate[1]["state"] = "PLANNED"
    duplicate[1] = seal_campaign_event(duplicate[1])
    cases["duplicate_transition"] = duplicate

    clock = json.loads(json.dumps(events[:2]))
    clock[1]["occurred_at"] = "2031-01-10T11:59:59+00:00"
    clock[1] = seal_campaign_event(clock[1])
    cases["clock_regression"] = clock

    source = json.loads(json.dumps(events[:2]))
    source[1]["source_event_id"] = "SYNTH-NFP-SUBSTITUTED"
    source[1] = seal_campaign_event(source[1])
    cases["source_substitution"] = source

    missing = json.loads(json.dumps(events[:2]))
    missing[1]["evidence_id"] = None
    missing[1] = seal_campaign_event(missing[1])
    cases["missing_evidence"] = missing

    tampered = json.loads(json.dumps(events))
    tampered[-1]["evidence_id"] = "tampered"
    cases["hash_tamper"] = tampered

    output: dict[str, dict[str, Any]] = {}
    for name, case in cases.items():
        audit = replay_campaign(case, specification)
        issue = expected[name]
        output[name] = {
            "passed": issue in audit["issues"],
            "expected_issue": issue,
            "issues": audit["issues"],
        }
    return output


def run_phase9(
    specification_path: Path,
    phase8_specification_path: Path,
    roster_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    specification = json.loads(specification_path.read_text(encoding="utf-8"))
    json.loads(phase8_specification_path.read_text(encoding="utf-8"))
    json.loads(roster_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / "campaign_events.jsonl"
    journal_path.unlink(missing_ok=True)
    journal = CampaignJournal(journal_path, specification)
    for event in _fixture_events(specification):
        journal.append(
            campaign_id=event["campaign_id"],
            source_event_id=event["source_event_id"],
            state=event["state"],
            occurred_at=event["occurred_at"],
            evidence_id=event["evidence_id"],
            provenance=event["provenance"],
        )
    events = journal.events()
    audit = replay_campaign(events, specification)
    failures = failure_injections(events, specification)
    gates = specification["completion_gates"]
    counts = {
        "synthetic_campaigns": 1,
        "synthetic_events": len(events),
        "structurally_complete_campaigns": int(
            audit["state"] == "EVIDENCE_ENROLLED" and audit["passed"]
        ),
        "empirical_campaigns": 0,
        "prospective_vendor_requests": 0,
    }
    checks = {
        name: counts[name] == gates[name]
        for name in (
            "synthetic_campaigns",
            "synthetic_events",
            "structurally_complete_campaigns",
            "empirical_campaigns",
            "prospective_vendor_requests",
        )
    }
    checks["journal_audit"] = audit["passed"]
    checks["failure_injections"] = len(failures) == gates["failure_injections"] and all(
        item["passed"] for item in failures.values()
    )
    summary = {
        "trial_id": specification["trial_id"],
        "phase9_status": "PIPELINE_EXECUTED",
        "decision": specification["decision"] if all(checks.values()) else "FAIL_PHASE9",
        "economic_decision": specification["economic_decision"],
        "counts": counts,
        "audit": audit,
        "checks": checks,
        "authenticated_vendor_request_executed": False,
        "market_price_join_executed": False,
        "price_model_executed": False,
    }
    _write_json(output_dir / "audit.json", audit)
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase9_summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "inputs": {
                manifest_key(path, project_root): sha256_path(path)
                for path in (
                    specification_path,
                    phase8_specification_path,
                    roster_path,
                )
            },
            "journal_sha256": sha256_path(journal_path),
            "journal_head_hash": audit["head_hash"],
        },
    )
    (output_dir / "PHASE9_REPORT.md").write_text(
        "# Phase 9 result\n\n"
        f"Decision: **{summary['decision']}**.\n\n"
        f"The synthetic campaign reached `{audit['state']}` with {len(events)} events. "
        "Empirical campaigns and vendor requests remain zero.\n",
        encoding="utf-8",
    )
    return summary
