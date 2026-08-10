from __future__ import annotations

import hashlib
import json
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
- 2024 pilot: 24 simultaneous-release bundles and 997,364 bid/ask ticks.
- Price-arrival study at +1s, +5s, +30s, +1m, +5m, +15m and +60m.
- One registered three-feature Ridge trial, +1m entry to +15m exit.
- Dynamic observed bid/ask plus a 1.0-pip round-trip slippage buffer.
- News, point-in-time consensus and official-source acquisition decision recorded.

## Experiment 0

Coverage was {experiment['coverage']['analyzed_events']} / {experiment['coverage']['scheduled_events']} events.
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
