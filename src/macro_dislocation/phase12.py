from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .forward_test import (
    ForwardJournal,
    record_paper_signal,
    replay_forward_events,
    risk_issues,
    seal_forward_event,
    settle_paper_signal,
)
from .verification_utils import manifest_key, sha256_path
from .walk_forward import load_labeled_rows


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def failure_injections(
    spec: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = spec["failure_injections"]
    policy = spec["policy"]
    base = dict(
        now="2025-01-01T00:00:00+00:00",
        quote_timestamp="2025-01-01T00:00:00+00:00",
        bid=100.0,
        ask=100.01,
        open_positions=0,
        daily_pnl_bp=0.0,
        kill_switch=False,
        policy=policy,
    )
    cases: dict[str, list[str]] = {}
    cases["kill_switch"] = risk_issues(**{**base, "kill_switch": True})
    cases["stale_quote"] = risk_issues(
        **{**base, "quote_timestamp": "2024-12-31T23:59:50+00:00"}
    )
    cases["wide_spread"] = risk_issues(**{**base, "ask": 100.20})
    cases["position_limit"] = risk_issues(**{**base, "open_positions": 1})
    cases["daily_loss_limit"] = risk_issues(**{**base, "daily_pnl_bp": -40.0})
    early = json.loads(json.dumps(events[:1]))
    signal = early[0]
    settlement = seal_forward_event(
        {
            "sequence": 2,
            "event_type": "SETTLEMENT",
            "occurred_at": signal["occurred_at"],
            "payload": {"signal_id": signal["payload"]["signal_id"]},
            "provenance": "synthetic_fixture",
            "previous_hash": signal["event_hash"],
        }
    )
    early.append(settlement)
    cases["early_settlement"] = replay_forward_events(early)["issues"]
    outcome = json.loads(json.dumps(events[:1]))
    outcome[0]["payload"]["target_mid_bp"] = 1.0
    outcome[0] = seal_forward_event(outcome[0])
    cases["outcome_at_signal"] = replay_forward_events(outcome)["issues"]
    tamper = json.loads(json.dumps(events))
    tamper[-1]["payload"]["net_return_bp"] = 999.0
    cases["journal_tamper"] = replay_forward_events(tamper)["issues"]
    return {
        name: {
            "passed": expected[name] in issues,
            "expected_issue": expected[name],
            "issues": issues,
        }
        for name, issues in cases.items()
    }


def signal_input_from_label(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "event_id",
        "evidence_package_id",
        "scheduled_at",
        "event_family",
        "feature_ready_at",
        "provenance",
        "entry_timestamp",
        "entry_bid",
        "entry_ask",
        "exit_timestamp",
        "headline_surprise",
        "revision_surprise",
        "internal_breadth",
        "regime_score",
        "pre_volatility_bp",
    }
    return {name: row[name] for name in allowed}


def run_phase12(
    specification_path: Path,
    phase11_specification_path: Path,
    labels_path: Path,
    model_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    spec = json.loads(specification_path.read_text())
    phase11_spec = json.loads(phase11_specification_path.read_text())
    model = json.loads(model_path.read_text())
    rows = load_labeled_rows(
        labels_path,
        horizon=int(phase11_spec["target_horizon_seconds"]),
        role=spec["dataset_role"],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / "forward_events.jsonl"
    journal_path.unlink(missing_ok=True)
    journal = ForwardJournal(journal_path)
    for row in rows:
        signal = record_paper_signal(
            journal,
            model,
            signal_input_from_label(row),
            now=row["entry_timestamp"],
            policy=spec["policy"],
            kill_switch=False,
            trade_threshold_bp=float(phase11_spec["model"]["trade_threshold_bp"]),
        )
        settle_paper_signal(
            journal,
            signal["payload"]["signal_id"],
            occurred_at=row["exit_timestamp"],
            exit_bid=float(row["exit_bid"]),
            exit_ask=float(row["exit_ask"]),
            provenance=row["provenance"],
        )
    events = journal.events()
    audit = replay_forward_events(events)
    failures = failure_injections(spec, events)
    gates = spec["completion_gates"]
    counts = {
        "synthetic_forward_signals": audit["signals"],
        "synthetic_forward_settlements": audit["settlements"],
        "prospective_forward_signals": 0,
        "prospective_forward_settlements": 0,
        "live_orders": 0,
    }
    checks = {name: counts[name] == gates[name] for name in counts}
    checks["journal_audit"] = audit["passed"] and audit["open_signals"] == 0
    checks["failure_injections"] = (
        len(failures) == gates["failure_injections"]
        and all(value["passed"] for value in failures.values())
    )
    checks["paper_only"] = all(
        event["payload"]["mode"] == "paper_only" for event in events
    )
    summary = {
        "trial_id": spec["trial_id"],
        "phase12_status": "FORWARD_HARNESS_EXECUTED",
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE12",
        "economic_decision": spec["economic_decision"],
        "counts": counts,
        "checks": checks,
        "audit": audit,
        "model_hash": model["model_hash"],
        "operator_kill_switch_for_fixture": False,
        "production_kill_switch_default": spec["policy"]["kill_switch_default"],
    }
    _write_json(output_dir / "audit.json", audit)
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase12_summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "inputs": {
                manifest_key(path, project_root): sha256_path(path)
                for path in (
                    specification_path,
                    phase11_specification_path,
                    labels_path,
                    model_path,
                )
            },
            "journal_sha256": sha256_path(journal_path),
            "journal_head_hash": audit["head_hash"],
        },
    )
    (output_dir / "PHASE12_REPORT.md").write_text(
        "# Phase 12 result\n\n"
        f"Decision: **{summary['decision']}**.\n\n"
        f"Recorded and settled {audit['signals']} synthetic paper signals. "
        "Prospective settlements and live orders remain zero.\n",
        encoding="utf-8",
    )
    return summary
