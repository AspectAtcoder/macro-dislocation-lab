from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .evidence_enrollment import EvidenceLedger
from .pit_prices import (
    build_labels,
    generate_quotes,
    align_quote_tape,
    load_feature_events,
    load_quote_tape,
    load_price_events,
    validate_pit_inputs,
    write_csv,
)
from .verification_utils import manifest_key, sha256_path


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def failure_injections(events: list[Any], quotes: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    expected = spec["failure_injections"]
    cases: dict[str, list[str]] = {}
    late = list(events)
    late[0] = replace(late[0], feature_ready_at="2024-01-05T13:31:01+00:00")
    cases["feature_after_anchor"] = validate_pit_inputs(late, quotes, spec)
    stale = json.loads(json.dumps(quotes))
    stale[0]["quote_lag_seconds"] = 3.0
    cases["stale_quote"] = validate_pit_inputs(events, stale, spec)
    crossed = json.loads(json.dumps(quotes))
    crossed[0]["bid"] = crossed[0]["ask"]
    cases["crossed_market"] = validate_pit_inputs(events, crossed, spec)
    duplicate = [*events, events[0]]
    cases["duplicate_event"] = validate_pit_inputs(duplicate, quotes, spec)
    cases["constant_cost"] = validate_pit_inputs(
        events, quotes, spec, cost_mode="constant"
    )
    nonfinite = json.loads(json.dumps(quotes))
    nonfinite[0]["bid"] = "nan"
    cases["nonfinite_value"] = validate_pit_inputs(events, nonfinite, spec)
    return {
        name: {
            "passed": expected[name] in issues,
            "expected_issue": expected[name],
            "issues": issues,
        }
        for name, issues in cases.items()
    }


def run_phase10(
    specification_path: Path,
    events_path: Path,
    phase9_specification_path: Path,
    output_dir: Path,
    *,
    project_root: Path,
) -> dict[str, Any]:
    spec = json.loads(specification_path.read_text(encoding="utf-8"))
    json.loads(phase9_specification_path.read_text(encoding="utf-8"))
    events = load_price_events(events_path)
    quotes = generate_quotes(events, spec)
    labels = build_labels(events, quotes, spec)
    failures = failure_injections(events, quotes, spec)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "quotes.csv", quotes)
    write_csv(output_dir / "labeled_events.csv", labels)
    gates = spec["completion_gates"]
    counts = {
        "events": len(events),
        "labeled_rows": len(labels),
        "quote_rows": len(quotes),
        "backtest_events": sum(event.dataset_role == "backtest" for event in events),
        "forward_events": sum(event.dataset_role == "forward" for event in events),
        "empirical_events": sum(
            event.provenance != "synthetic_fixture" for event in events
        ),
    }
    checks = {
        name: counts[name] == gates[name]
        for name in (
            "labeled_rows",
            "quote_rows",
            "backtest_events",
            "forward_events",
            "empirical_events",
        )
    }
    checks["failure_injections"] = len(failures) == gates["failure_injections"] and all(
        value["passed"] for value in failures.values()
    )
    checks["dynamic_costs"] = all(
        row["cost_model"] == "dynamic_spread_volatility_v1" for row in labels
    )
    summary = {
        "trial_id": spec["trial_id"],
        "phase10_status": "PIPELINE_EXECUTED",
        "decision": spec["decision"] if all(checks.values()) else "FAIL_PHASE10",
        "economic_decision": spec["economic_decision"],
        "counts": counts,
        "checks": checks,
        "horizons": spec["timing"],
        "price_join_provenance": "synthetic_only",
    }
    _write_json(output_dir / "failure_injections.json", failures)
    _write_json(output_dir / "phase10_summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "inputs": {
                manifest_key(path, project_root): sha256_path(path)
                for path in (specification_path, events_path, phase9_specification_path)
            },
            "quotes_sha256": sha256_path(output_dir / "quotes.csv"),
            "labels_sha256": sha256_path(output_dir / "labeled_events.csv"),
        },
    )
    (output_dir / "PHASE10_REPORT.md").write_text(
        "# Phase 10 result\n\n"
        f"Decision: **{summary['decision']}**.\n\n"
        f"Generated {len(labels)} synthetic PIT labels from {len(quotes)} quote rows. "
        "Empirical price joins remain zero.\n",
        encoding="utf-8",
    )
    return summary


def build_empirical_pit_labels(
    specification_path: Path,
    feature_events_path: Path,
    quote_tape_path: Path,
    evidence_ledger_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    spec = json.loads(specification_path.read_text(encoding="utf-8"))
    events = load_feature_events(feature_events_path)
    packages = {
        package["package_id"]: package
        for package in EvidenceLedger(evidence_ledger_path).packages()
    }
    if not packages:
        raise ValueError("empty_evidence_ledger")
    for event in events:
        package = packages.get(event.evidence_package_id)
        if package is None:
            raise ValueError("evidence_package_not_enrolled")
        if package.get("enrollable") is not True or package.get("issues") != []:
            raise ValueError("evidence_package_not_enrollable")
        if package.get("scheduled_at") != event.scheduled_at:
            raise ValueError("evidence_schedule_mismatch")
        if str(package.get("event_family") or "").upper() != event.event_family.upper():
            raise ValueError("evidence_event_family_mismatch")
    tape = load_quote_tape(quote_tape_path, asset=spec["asset"])
    if any(row["provenance"] == "synthetic_fixture" for row in tape):
        raise ValueError("empirical PIT builder rejects synthetic quote provenance")
    quotes = align_quote_tape(events, tape, spec)
    labels = build_labels(events, quotes, spec)
    if any(row["provenance"] == "synthetic_fixture" for row in labels):
        raise ValueError("empirical PIT builder rejects synthetic provenance")
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "quotes.csv", quotes)
    write_csv(output_dir / "labeled_events.csv", labels)
    summary = {
        "status": "EMPIRICAL_PIT_LABELS_BUILT",
        "events": len(events),
        "labels": len(labels),
        "quote_rows": len(quotes),
        "asset": spec["asset"],
        "cost_model": "dynamic_spread_volatility_v1",
        "evidence_packages": len({event.evidence_package_id for event in events}),
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(
        output_dir / "manifest.json",
        {
            "inputs": {
                "specification": sha256_path(specification_path),
                "feature_events": sha256_path(feature_events_path),
                "quote_tape": sha256_path(quote_tape_path),
                "evidence_ledger": sha256_path(
                    evidence_ledger_path / "evidence.jsonl"
                ),
            },
            "quotes_sha256": sha256_path(output_dir / "quotes.csv"),
            "labels_sha256": sha256_path(output_dir / "labeled_events.csv"),
            "evidence_package_ids": sorted(
                {event.evidence_package_id for event in events}
            ),
        },
    )
    return summary
