from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from .models import Quote, Target

HORIZONS = (1, 5, 30, 60, 300, 900, 3600)


def read_quotes(path: Path) -> Iterator[Quote]:
    previous: datetime | None = None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp = datetime.fromisoformat(row["timestamp_utc"]).astimezone(UTC)
            if previous is not None and timestamp < previous:
                raise ValueError("quote CSV must be sorted by timestamp")
            previous = timestamp
            yield Quote(timestamp, float(row["bid"]), float(row["ask"]))


def read_events(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: row["release_timestamp_utc"])
    return rows


def resolve_targets(
    quotes: Iterable[Quote], targets: Iterable[Target], *, max_staleness_seconds: float = 10.0
) -> dict[tuple[str, str], Quote]:
    pending = sorted(targets, key=lambda target: target.timestamp_utc)
    resolved: dict[tuple[str, str], Quote] = {}
    index = 0
    previous: Quote | None = None
    for quote in quotes:
        while index < len(pending) and quote.timestamp_utc >= pending[index].timestamp_utc:
            target = pending[index]
            chosen = previous if target.side == "before" else quote
            if chosen is not None:
                lag = abs((chosen.timestamp_utc - target.timestamp_utc).total_seconds())
                strict_before_ok = target.side != "before" or chosen.timestamp_utc < target.timestamp_utc
                if lag <= max_staleness_seconds and strict_before_ok:
                    resolved[(target.event_id, target.label)] = chosen
            index += 1
        previous = quote
    return resolved


def _return_bps(start: float, end: float) -> float:
    return (end / start - 1.0) * 10_000.0


def _signed(value: float, epsilon: float = 1e-12) -> int:
    return 1 if value > epsilon else -1 if value < -epsilon else 0


def event_metrics(
    event: dict[str, str],
    points: dict[str, Quote],
    *,
    final_horizon: int = 3600,
    min_final_move_bps: float = 2.0,
) -> list[dict[str, str | float | int]]:
    baseline = points["t0"]
    event_time = datetime.fromisoformat(event["release_timestamp_utc"]).astimezone(UTC)
    final = points[f"h{final_horizon}"]
    final_return = _return_bps(baseline.mid, final.mid)
    denominator_ok = abs(final_return) >= min_final_move_bps
    rows: list[dict[str, str | float | int]] = []
    for horizon in HORIZONS:
        quote = points[f"h{horizon}"]
        target_time = event_time + timedelta(seconds=horizon)
        cumulative = _return_bps(baseline.mid, quote.mid)
        residual = _return_bps(quote.mid, final.mid)
        raw_arrival = cumulative / final_return if denominator_ok else math.nan
        completion = (
            max(0.0, 1.0 - abs(final_return - cumulative) / abs(final_return))
            if denominator_ok
            else math.nan
        )
        direction_agrees = (
            int(_signed(cumulative) == _signed(final_return)) if denominator_ok else -1
        )
        residual_continues = (
            int(_signed(cumulative) == _signed(residual))
            if _signed(cumulative) and _signed(residual)
            else -1
        )
        long_net = (final.bid - quote.ask) / quote.mid * 10_000.0
        short_net = (quote.bid - final.ask) / quote.mid * 10_000.0
        rows.append(
            {
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "release_timestamp_utc": event["release_timestamp_utc"],
                "horizon_seconds": horizon,
                "baseline_quote_timestamp_utc": baseline.timestamp_utc.isoformat(),
                "baseline_lead_ms": (event_time - baseline.timestamp_utc).total_seconds()
                * 1_000.0,
                "horizon_quote_timestamp_utc": quote.timestamp_utc.isoformat(),
                "horizon_lag_ms": (quote.timestamp_utc - target_time).total_seconds() * 1_000.0,
                "baseline_mid": baseline.mid,
                "horizon_mid": quote.mid,
                "final_mid": final.mid,
                "cumulative_return_bps": cumulative,
                "final_return_bps": final_return,
                "residual_to_final_bps": residual,
                "arrival_ratio": raw_arrival,
                "completion_ratio": completion,
                "direction_agrees": direction_agrees,
                "residual_continues_initial": residual_continues,
                "spread_pips": quote.spread * 100.0,
                "long_residual_net_bps": long_net,
                "short_residual_net_bps": short_net,
                "denominator_ok": int(denominator_ok),
            }
        )
    return rows


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def summarize(rows: list[dict[str, str | float | int]]) -> dict[str, object]:
    grouped: dict[tuple[str, int], list[dict[str, str | float | int]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["event_type"]), int(row["horizon_seconds"]))].append(row)
    summaries: list[dict[str, object]] = []
    for (event_type, horizon), group in sorted(grouped.items()):
        usable = [row for row in group if int(row["denominator_ok"]) == 1]
        completion = [float(row["completion_ratio"]) for row in usable]
        arrival = [float(row["arrival_ratio"]) for row in usable]
        residual_abs = [abs(float(row["residual_to_final_bps"])) for row in group]
        direction = [int(row["direction_agrees"]) for row in usable]
        continuation = [
            int(row["residual_continues_initial"])
            for row in group
            if int(row["residual_continues_initial"]) >= 0
        ]
        spreads = [float(row["spread_pips"]) for row in group]
        summaries.append(
            {
                "event_type": event_type,
                "horizon_seconds": horizon,
                "events": len(group),
                "usable_final_moves": len(usable),
                "median_completion_pct": 100.0 * statistics.median(completion)
                if completion
                else None,
                "median_arrival_pct": 100.0 * statistics.median(arrival) if arrival else None,
                "arrival_p25_pct": 100.0 * _quantile(arrival, 0.25) if arrival else None,
                "arrival_p75_pct": 100.0 * _quantile(arrival, 0.75) if arrival else None,
                "direction_agreement_pct": 100.0 * sum(direction) / len(direction)
                if direction
                else None,
                "residual_continuation_pct": 100.0 * sum(continuation) / len(continuation)
                if continuation
                else None,
                "median_abs_residual_bps": statistics.median(residual_abs)
                if residual_abs
                else None,
                "median_spread_pips": statistics.median(spreads) if spreads else None,
                "max_spread_pips": max(spreads) if spreads else None,
            }
        )
    five_minute = [
        item
        for item in summaries
        if item["horizon_seconds"] == 300 and item["median_completion_pct"] is not None
    ]
    all_over_95 = bool(five_minute) and all(
        float(item["median_completion_pct"]) >= 95.0 for item in five_minute
    )
    baseline_rows = [row for row in rows if int(row["horizon_seconds"]) == HORIZONS[0]]
    horizon_lags = [float(row["horizon_lag_ms"]) for row in rows]
    baseline_leads = [float(row["baseline_lead_ms"]) for row in baseline_rows]
    return {
        "definition": {
            "final_horizon_seconds": 3600,
            "completion": "max(0, 1 - abs(R_final - R_h) / abs(R_final))",
            "denominator_filter": "abs(60m return) >= configured threshold",
            "costs": "observed Dukascopy bid/ask; no commission or additional slippage",
        },
        "groups": summaries,
        "screen": {
            "jump_capture_at_5m": "NO_GO" if all_over_95 else "REVIEW",
            "reason": (
                "Median 5-minute completion is at least 95% for every event type."
                if all_over_95
                else "At least one event type retains a descriptive post-5-minute residual. Statistical validation is still required."
            ),
        },
        "data_quality": {
            "median_horizon_quote_lag_ms": statistics.median(horizon_lags)
            if horizon_lags
            else None,
            "max_horizon_quote_lag_ms": max(horizon_lags) if horizon_lags else None,
            "median_baseline_quote_lead_ms": statistics.median(baseline_leads)
            if baseline_leads
            else None,
            "max_baseline_quote_lead_ms": max(baseline_leads) if baseline_leads else None,
            "selection_tolerance_ms": 10_000,
        },
    }


def _fmt(value: object, digits: int = 1) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def write_markdown_report(summary: dict[str, object], path: Path) -> None:
    coverage = summary["coverage"]
    screen = summary["screen"]
    lines = [
        "# Experiment 0 — USD/JPY, CPI and NFP (2024)",
        "",
        "> Descriptive Phase-0 result only. Twenty-four scheduled events cannot establish a tradable edge.",
        "",
        f"Coverage: **{coverage['analyzed_events']} / {coverage['scheduled_events']} events**. ",
        f"Jump-capture screen: **{screen['jump_capture_at_5m']}**.",
        "",
        str(screen["reason"]),
        "",
        "| Event | Horizon | N usable | Median completion | Median raw arrival | Residual continuation | Median abs residual | Median spread |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {1: "1s", 5: "5s", 30: "30s", 60: "1m", 300: "5m", 900: "15m", 3600: "60m"}
    for item in summary["groups"]:
        lines.append(
            "| {event} | {horizon} | {n} | {completion}% | {arrival}% | {continuation}% | {residual} bp | {spread} pips |".format(
                event=item["event_type"],
                horizon=labels[int(item["horizon_seconds"])],
                n=item["usable_final_moves"],
                completion=_fmt(item["median_completion_pct"]),
                arrival=_fmt(item["median_arrival_pct"]),
                continuation=_fmt(item["residual_continuation_pct"]),
                residual=_fmt(item["median_abs_residual_bps"], 2),
                spread=_fmt(item["median_spread_pips"], 2),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- +60m is a measurement reference, not proof of a permanent fair value.",
            "- Arrival ratios exclude events with an absolute +60m move below 2bp.",
            "- Bid/ask is observed, but latency, last-look, rejection, commission and extra slippage are not modeled.",
            "- The consensus bootstrap source has timestamp defects; BLS release times replace its intraday times.",
            "- Any residual signal must survive a longer point-in-time sample, a sealed holdout, and trial-count correction.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_completion_svg(summary: dict[str, object], path: Path) -> None:
    width, height = 900, 520
    left, right, top, bottom = 85, 35, 45, 85
    plot_w, plot_h = width - left - right, height - top - bottom
    horizons = list(HORIZONS)
    x_for = {h: left + index * plot_w / (len(horizons) - 1) for index, h in enumerate(horizons)}
    y_for = lambda value: top + (100.0 - max(0.0, min(100.0, value))) * plot_h / 100.0
    by_event: dict[str, dict[int, float]] = defaultdict(dict)
    for item in summary["groups"]:
        value = item["median_completion_pct"]
        if value is not None:
            by_event[str(item["event_type"])][int(item["horizon_seconds"])] = float(value)
    colors = {"CPI": "#2563eb", "NFP": "#ea580c"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="85" y="28" font-family="sans-serif" font-size="20" font-weight="700">Median completion toward +60m USD/JPY level</text>',
    ]
    for tick in (0, 25, 50, 75, 95, 100):
        y = y_for(float(tick))
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12" fill="#4b5563">{tick}%</text>')
    labels = {1: "1s", 5: "5s", 30: "30s", 60: "1m", 300: "5m", 900: "15m", 3600: "60m"}
    for horizon in horizons:
        x = x_for[horizon]
        parts.append(f'<text x="{x:.1f}" y="{height-bottom+28}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#4b5563">{labels[horizon]}</text>')
    parts.append(f'<line x1="{left}" y1="{y_for(95):.1f}" x2="{width-right}" y2="{y_for(95):.1f}" stroke="#dc2626" stroke-dasharray="5 5"/>')
    for event_type, values in sorted(by_event.items()):
        points = [(x_for[h], y_for(values[h])) for h in horizons if h in values]
        if not points:
            continue
        color = colors.get(event_type, "#111827")
        path_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        parts.append(f'<polyline points="{path_points}" fill="none" stroke="{color}" stroke-width="3"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
    legend_x = width - right - 150
    for index, event_type in enumerate(sorted(by_event)):
        y = 25 + index * 20
        color = colors.get(event_type, "#111827")
        parts.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x+25}" y2="{y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+32}" y="{y+4}" font-family="sans-serif" font-size="12">{event_type}</text>')
    parts.extend(
        [
            f'<text x="{left+plot_w/2:.1f}" y="{height-18}" text-anchor="middle" font-family="sans-serif" font-size="13">Time after scheduled release</text>',
            f'<text x="18" y="{top+plot_h/2:.1f}" text-anchor="middle" font-family="sans-serif" font-size="13" transform="rotate(-90 18 {top+plot_h/2:.1f})">Completion ratio</text>',
            '</svg>',
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def run_experiment(
    quotes_path: Path,
    events_path: Path,
    output_dir: Path,
    *,
    min_final_move_bps: float = 2.0,
) -> dict[str, object]:
    events = read_events(events_path)
    targets: list[Target] = []
    for event in events:
        event_time = datetime.fromisoformat(event["release_timestamp_utc"]).astimezone(UTC)
        targets.append(Target(event_time, event["event_id"], "t0", "before"))
        targets.extend(
            Target(event_time + timedelta(seconds=h), event["event_id"], f"h{h}", "after")
            for h in HORIZONS
        )
    resolved = resolve_targets(read_quotes(quotes_path), targets)
    metric_rows: list[dict[str, str | float | int]] = []
    missing: list[str] = []
    for event in events:
        points = {
            label: resolved[(event["event_id"], label)]
            for label in ["t0", *(f"h{h}" for h in HORIZONS)]
            if (event["event_id"], label) in resolved
        }
        required = {"t0", *(f"h{h}" for h in HORIZONS)}
        if set(points) != required:
            missing.append(event["event_id"])
            continue
        metric_rows.extend(
            event_metrics(event, points, min_final_move_bps=min_final_move_bps)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "event_metrics.csv"
    if metric_rows:
        with metrics_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(metric_rows[0]))
            writer.writeheader()
            writer.writerows(metric_rows)
    result = summarize(metric_rows)
    result["coverage"] = {
        "scheduled_events": len(events),
        "analyzed_events": len(events) - len(missing),
        "missing_events": missing,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown_report(result, output_dir / "report.md")
    write_completion_svg(result, output_dir / "arrival_curve.svg")
    return result
