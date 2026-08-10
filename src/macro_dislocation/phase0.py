from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
from datetime import UTC, datetime
from pathlib import Path

from .baseline import run_baseline
from .experiment import run_experiment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_inputs(events_path: Path, quotes_path: Path) -> dict[str, object]:
    with events_path.open(newline="", encoding="utf-8") as handle:
        events = list(csv.DictReader(handle))
    event_ids = [row["event_id"] for row in events]
    event_types: dict[str, int] = {}
    missing_primary = 0
    for row in events:
        event_types[row["event_type"]] = event_types.get(row["event_type"], 0) + 1
        primary = (
            row.get("cpi_mom_actual_pct", "")
            if row["event_type"] == "CPI"
            else row.get("nfp_change_actual_k", "")
        )
        forecast = (
            row.get("cpi_mom_forecast_pct", "")
            if row["event_type"] == "CPI"
            else row.get("nfp_change_forecast_k", "")
        )
        missing_primary += int(not primary or not forecast)

    quote_count = crossed = out_of_order = duplicate_timestamps = 0
    previous: datetime | None = None
    first: datetime | None = None
    last: datetime | None = None
    minimum_spread = math.inf
    maximum_spread = -math.inf
    sources: dict[str, int] = {}
    with quotes_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp_utc"]).astimezone(UTC)
            bid, ask = float(row["bid"]), float(row["ask"])
            quote_count += 1
            crossed += int(bid > ask)
            out_of_order += int(previous is not None and timestamp < previous)
            duplicate_timestamps += int(previous == timestamp)
            previous = timestamp
            first = first or timestamp
            last = timestamp
            spread_pips = (ask - bid) * 100.0
            minimum_spread = min(minimum_spread, spread_pips)
            maximum_spread = max(maximum_spread, spread_pips)
            source = row.get("source", "unknown")
            sources[source] = sources.get(source, 0) + 1
    valid = all(
        [
            len(events) == 24,
            len(set(event_ids)) == len(event_ids),
            event_types == {"NFP": 12, "CPI": 12},
            missing_primary == 0,
            quote_count > 0,
            crossed == 0,
            out_of_order == 0,
        ]
    )
    return {
        "valid": valid,
        "events": {
            "rows": len(events),
            "unique_event_ids": len(set(event_ids)),
            "by_type": event_types,
            "missing_primary_actual_or_forecast": missing_primary,
        },
        "quotes": {
            "rows": quote_count,
            "crossed": crossed,
            "out_of_order": out_of_order,
            "adjacent_duplicate_timestamps": duplicate_timestamps,
            "first_timestamp_utc": first.isoformat() if first else None,
            "last_timestamp_utc": last.isoformat() if last else None,
            "minimum_spread_pips": minimum_spread if quote_count else None,
            "maximum_spread_pips": maximum_spread if quote_count else None,
            "sources": sources,
        },
    }


def _group(summary: dict[str, object], event_type: str, horizon: int) -> dict[str, object]:
    return next(
        item
        for item in summary["groups"]
        if item["event_type"] == event_type and int(item["horizon_seconds"]) == horizon
    )


def _pct(value: object) -> str:
    return f"{100.0 * float(value):.1f}%"


def _number(value: object, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def _write_report(summary: dict[str, object], path: Path) -> None:
    experiment = summary["experiment0"]
    baseline = summary["baseline"]
    cpi_5m = _group(experiment, "CPI", 300)
    nfp_5m = _group(experiment, "NFP", 300)
    test = baseline["test"]
    decision = summary["decision"]
    report = f"""# Phase 0 completion report

Status: **{summary['phase0_status']}**

Next-phase decision: **{decision['phase1']}**

Current strategy specification: **{decision['current_numeric_specification']}**

## Scope completed

- USD/JPY, U.S. CPI and Employment Situation only.
- 2024 pilot: 24 simultaneous-release bundles and {int(summary['data_audit']['quotes']['rows']):,} bid/ask ticks.
- Price-arrival study at +1s, +5s, +30s, +1m, +5m, +15m and +60m.
- One registered three-feature Ridge trial, +1m entry to +15m exit.
- Dynamic observed bid/ask plus a 1.0-pip round-trip slippage buffer.
- News, point-in-time consensus and official-source acquisition decision recorded.

## Experiment 0

Coverage was {experiment['coverage']['analyzed_events']} / {experiment['coverage']['scheduled_events']} events.
Maximum selected-quote lag was {_number(experiment['data_quality']['max_horizon_quote_lag_ms'], 0)} ms;
maximum pre-release baseline lead was {_number(experiment['data_quality']['max_baseline_quote_lead_ms'], 0)} ms.
Median +5m completion toward the +60m level was
{_number(cpi_5m['median_completion_pct'], 1)}% for CPI and
{_number(nfp_5m['median_completion_pct'], 1)}% for NFP. Median absolute residual
to +60m was {_number(cpi_5m['median_abs_residual_bps'])} bp and
{_number(nfp_5m['median_abs_residual_bps'])} bp respectively.

The release jump is not an execution target. Median +1s spreads were
{_number(_group(experiment, 'CPI', 1)['median_spread_pips'])} pips for CPI and
{_number(_group(experiment, 'NFP', 1)['median_spread_pips'])} pips for NFP.

## Registered residual model

- Train/test: {baseline['train']['events']} / {test['events']} chronological events; no test-period refit.
- Direction: {test['sign_successes']} / {test['events']} = {_pct(test['sign_accuracy'])}.
- 95% Wilson interval: {_pct(test['sign_accuracy_wilson_95'][0])} to {_pct(test['sign_accuracy_wilson_95'][1])}.
- Exploratory two-sided binomial p-value versus 50%: {_number(test['sign_binomial_p_value_vs_50'], 4)}.
- MAE: model {_number(test['mae_model_bps'])} bp; zero forecast {_number(test['mae_zero_forecast_bps'])} bp; train-mean forecast {_number(test['mae_train_mean_forecast_bps'])} bp.
- Median net after observed bid/ask and slippage buffer: {_number(test['median_net_after_buffer_bps'])} bp.
- Predictive trace gate: **{baseline['status']}**.

This is a pilot diagnostic, not confirmatory evidence. The aggregate 2024 result was
already inspected before the model trial, and twelve test events cannot establish
an edge. Deflated Sharpe Ratio is intentionally not reported.

## Gate decision

- Data availability: **PASS for a research prototype**. A licensed production PIT
  consensus/news contract remains unpurchased.
- Jump capture: **NO-GO**.
- Residual magnitude: **PASS for further measurement**, not for trading.
- Current three-feature numeric model: **{decision['current_numeric_specification']}**.
- Phase 1: **{decision['phase1']}**.

{decision['reason']}

Any next model is a new registered trial. It may add text-derived event axes or a
larger cross-country/event universe, but must not tune this 2024 pilot repeatedly.
The multi-day to two-week position model is outside Phase 0 and remains unvalidated.

## Data-source decision

MVP: paid Trading Economics PIT calendar plus Federal Reserve, BLS/BEA, EIA and OPEC
official sources. If a later gate passes, evaluate LSEG Machine Readable News plus
Real-Time Economics; Bloomberg Event-Driven Feeds plus ECO is the alternative.
Machine-learning, embedding, retention and derived-data rights must be contractual.
"""
    path.write_text(report, encoding="utf-8")


def run_phase0(
    events_path: Path,
    quotes_path: Path,
    specification_path: Path,
    news_sources_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    news_sources = json.loads(news_sources_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    data_audit = audit_inputs(events_path, quotes_path)
    if not data_audit["valid"]:
        raise ValueError(f"input data audit failed: {data_audit}")
    (output_dir / "data_audit.json").write_text(
        json.dumps(data_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    experiment = run_experiment(
        quotes_path, events_path, output_dir / "experiment0", min_final_move_bps=2.0
    )
    baseline = run_baseline(
        events_path,
        output_dir / "experiment0" / "event_metrics.csv",
        specification_path,
        output_dir / "baseline",
    )
    coverage_pass = (
        experiment["coverage"]["analyzed_events"]
        / experiment["coverage"]["scheduled_events"]
        >= 0.90
    )
    residual_pass = all(
        float(_group(experiment, event_type, 300)["median_abs_residual_bps"]) >= 5.0
        for event_type in ("CPI", "NFP")
    )
    trace_present = baseline["status"] == "TRACE_PRESENT"
    if coverage_pass and residual_pass and trace_present:
        phase1 = "CONDITIONAL_GO_LIMITED_PIT_DATA_TRIAL"
        current = "PILOT_TRACE_PRESENT_NOT_VALIDATED"
        reason = (
            "A limited, contract-reviewed historical PIT data trial is justified. "
            "No live capital or full data commitment is justified by this sample."
        )
    else:
        phase1 = "NO_GO_CURRENT_NUMERIC_SPECIFICATION"
        current = "NO_PREDICTIVE_TRACE"
        reason = (
            "Do not expand or trade the current numeric specification. A text-based "
            "or cross-event model would be a distinct hypothesis requiring a new trial."
        )
    summary: dict[str, object] = {
        "phase0_status": "COMPLETE",
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "data_audit": data_audit,
        "experiment0": experiment,
        "baseline": baseline,
        "gates": {
            "coverage_90_pct": coverage_pass,
            "residual_magnitude_5bp_at_5m": residual_pass,
            "registered_baseline_trace": trace_present,
            "news_source_decision_recorded": bool(news_sources.get("mvp")),
        },
        "decision": {
            "jump_capture": "NO_GO",
            "current_numeric_specification": current,
            "phase1": phase1,
            "reason": reason,
        },
        "limitations": [
            "2024 is a pilot and cannot be reused as a final untouched holdout",
            "Dukascopy is one FX feed, not a consolidated tape",
            "calendar consensus source is research-only and not guaranteed point-in-time",
            "broker-specific latency, last look, rejection and fills are unavailable",
            "multi-day to two-week direction was not tested",
        ],
    }
    (output_dir / "phase0_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(summary, output_dir / "PHASE0_REPORT.md")
    manifest = {
        "generated_at_utc": summary["completed_at_utc"],
        "python": platform.python_version(),
        "inputs": {
            str(events_path): _sha256(events_path),
            str(quotes_path): _sha256(quotes_path),
            str(specification_path): _sha256(specification_path),
            str(news_sources_path): _sha256(news_sources_path),
        },
        "outputs": [
            "phase0_summary.json",
            "PHASE0_REPORT.md",
            "data_audit.json",
            "experiment0/event_metrics.csv",
            "experiment0/summary.json",
            "experiment0/arrival_curve.svg",
            "baseline/predictions.csv",
            "baseline/summary.json",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary
