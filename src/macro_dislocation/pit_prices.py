from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
FEATURE_NAMES = (
    "headline_surprise",
    "revision_surprise",
    "internal_breadth",
    "regime_score",
    "pre_volatility_bp",
)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be offset-aware")
    return parsed.astimezone(UTC)


def _finite(value: str | float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite_numeric_value")
    return number


@dataclass(frozen=True, slots=True)
class PriceEvent:
    event_id: str
    evidence_package_id: str
    scheduled_at: str
    event_family: str
    feature_ready_at: str
    features: tuple[float, ...]
    anchor_mid: float
    residual_15m_bp: float
    residual_60m_bp: float
    spreads_bp: tuple[float, float, float]
    dataset_role: str
    provenance: str


@dataclass(frozen=True, slots=True)
class PitFeatureEvent:
    event_id: str
    evidence_package_id: str
    scheduled_at: str
    event_family: str
    feature_ready_at: str
    features: tuple[float, ...]
    dataset_role: str
    provenance: str


def load_feature_events(path: Path) -> list[PitFeatureEvent]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    events: list[PitFeatureEvent] = []
    seen: set[str] = set()
    previous: datetime | None = None
    for row in rows:
        event_id = row["event_id"]
        evidence_package_id = str(row.get("evidence_package_id") or "").strip()
        if not evidence_package_id:
            raise ValueError("missing_evidence_package_id")
        if event_id in seen:
            raise ValueError("duplicate_event_id")
        seen.add(event_id)
        scheduled = parse_utc(row["scheduled_at"])
        feature_ready = parse_utc(row["feature_ready_at"])
        if feature_ready < scheduled:
            raise ValueError("feature_ready_before_release")
        if previous is not None and scheduled <= previous:
            raise ValueError("events_not_strictly_chronological")
        previous = scheduled
        events.append(
            PitFeatureEvent(
                event_id=event_id,
                evidence_package_id=evidence_package_id,
                scheduled_at=scheduled.isoformat(),
                event_family=row["event_family"],
                feature_ready_at=feature_ready.isoformat(),
                features=tuple(_finite(row[name]) for name in FEATURE_NAMES),
                dataset_role=row["dataset_role"],
                provenance=row["provenance"],
            )
        )
        if events[-1].dataset_role not in {"backtest", "forward"}:
            raise ValueError("invalid_dataset_role")
        if not events[-1].event_family.strip() or not events[-1].provenance.strip():
            raise ValueError("missing_feature_provenance")
    return events


def load_quote_tape(path: Path, *, asset: str) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        raw = list(csv.DictReader(handle))
    quotes: list[dict[str, Any]] = []
    previous: datetime | None = None
    for row in raw:
        if row["asset"] != asset:
            continue
        timestamp = parse_utc(row["timestamp"])
        if previous is not None and timestamp < previous:
            raise ValueError("quote_tape_not_chronological")
        previous = timestamp
        bid, ask = _finite(row["bid"]), _finite(row["ask"])
        if bid <= 0 or ask <= bid:
            raise ValueError("invalid_bid_ask")
        quotes.append(
            {
                "timestamp": timestamp.isoformat(),
                "bid": bid,
                "ask": ask,
                "asset": asset,
                "provenance": row["provenance"],
            }
        )
        if not quotes[-1]["provenance"].strip():
            raise ValueError("missing_quote_provenance")
    if not quotes:
        raise ValueError("quote_tape_empty")
    return quotes


def align_quote_tape(
    events: list[PitFeatureEvent],
    tape: list[dict[str, Any]],
    specification: dict[str, Any],
) -> list[dict[str, Any]]:
    horizons = [
        int(specification["timing"]["anchor_seconds_after_release"]),
        *[int(value) for value in specification["timing"]["exit_seconds_after_release"]],
    ]
    max_lag = float(specification["timing"]["maximum_quote_lag_seconds"])
    output: list[dict[str, Any]] = []
    cursor = 0
    for event in events:
        scheduled = parse_utc(event.scheduled_at)
        for horizon in horizons:
            target = scheduled + timedelta(seconds=horizon)
            while cursor < len(tape) and parse_utc(tape[cursor]["timestamp"]) < target:
                cursor += 1
            if cursor >= len(tape):
                raise ValueError("missing_quote_horizon")
            quote = tape[cursor]
            timestamp = parse_utc(quote["timestamp"])
            lag = (timestamp - target).total_seconds()
            if lag < 0 or lag > max_lag:
                raise ValueError("quote_lag_exceeded")
            mid = (quote["bid"] + quote["ask"]) / 2.0
            output.append(
                {
                    "event_id": event.event_id,
                    "timestamp": quote["timestamp"],
                    "horizon_seconds": horizon,
                    "bid": quote["bid"],
                    "ask": quote["ask"],
                    "mid": mid,
                    "spread_bp": (quote["ask"] - quote["bid"]) / mid * 10_000.0,
                    "quote_lag_seconds": lag,
                    "provenance": event.provenance,
                    "quote_provenance": quote["provenance"],
                }
            )
    return output


def load_price_events(path: Path) -> list[PriceEvent]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    events: list[PriceEvent] = []
    seen: set[str] = set()
    previous: datetime | None = None
    for row in rows:
        event_id = row["event_id"]
        if event_id in seen:
            raise ValueError("duplicate_event_id")
        seen.add(event_id)
        scheduled = parse_utc(row["scheduled_at"])
        if previous is not None and scheduled <= previous:
            raise ValueError("events_not_strictly_chronological")
        previous = scheduled
        features = tuple(_finite(row[name]) for name in FEATURE_NAMES)
        event = PriceEvent(
            event_id=event_id,
            evidence_package_id=(
                str(row.get("evidence_package_id") or "").strip()
                or f"synthetic-evidence:{event_id}"
            ),
            scheduled_at=scheduled.isoformat(),
            event_family=row["event_family"],
            feature_ready_at=parse_utc(row["feature_ready_at"]).isoformat(),
            features=features,
            anchor_mid=_finite(row["anchor_mid"]),
            residual_15m_bp=_finite(row["residual_15m_bp"]),
            residual_60m_bp=_finite(row["residual_60m_bp"]),
            spreads_bp=(
                _finite(row["entry_spread_bp"]),
                _finite(row["exit15_spread_bp"]),
                _finite(row["exit60_spread_bp"]),
            ),
            dataset_role=row["dataset_role"],
            provenance=row["provenance"],
        )
        if event.anchor_mid <= 0 or any(value <= 0 for value in event.spreads_bp):
            raise ValueError("invalid_bid_ask")
        if event.dataset_role not in {"backtest", "forward"}:
            raise ValueError("invalid_dataset_role")
        events.append(event)
    return events


def quote_from_mid(
    event_id: str,
    timestamp: datetime,
    horizon_seconds: int,
    mid: float,
    spread_bp: float,
    provenance: str,
) -> dict[str, Any]:
    half = mid * spread_bp / 20_000.0
    bid, ask = mid - half, mid + half
    if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or bid >= ask:
        raise ValueError("invalid_bid_ask")
    return {
        "event_id": event_id,
        "timestamp": timestamp.isoformat(),
        "horizon_seconds": horizon_seconds,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bp": spread_bp,
        "quote_lag_seconds": 0.0,
        "provenance": provenance,
        "quote_provenance": provenance,
    }


def generate_quotes(
    events: list[PriceEvent], specification: dict[str, Any]
) -> list[dict[str, Any]]:
    anchor_seconds = int(specification["timing"]["anchor_seconds_after_release"])
    exit_seconds = [int(value) for value in specification["timing"]["exit_seconds_after_release"]]
    quotes: list[dict[str, Any]] = []
    for event in events:
        scheduled = parse_utc(event.scheduled_at)
        mids = (
            event.anchor_mid,
            event.anchor_mid * (1.0 + event.residual_15m_bp / 10_000.0),
            event.anchor_mid * (1.0 + event.residual_60m_bp / 10_000.0),
        )
        horizons = (anchor_seconds, *exit_seconds)
        for horizon, mid, spread in zip(horizons, mids, event.spreads_bp):
            quotes.append(
                quote_from_mid(
                    event.event_id,
                    scheduled + timedelta(seconds=horizon),
                    horizon,
                    mid,
                    spread,
                    event.provenance,
                )
            )
    return quotes


def dynamic_slippage_bp(spread_bp: float, pre_volatility_bp: float) -> float:
    return 0.25 * spread_bp + 0.10 * pre_volatility_bp


def validate_pit_inputs(
    events: list[PriceEvent],
    quotes: list[dict[str, Any]],
    specification: dict[str, Any],
    *,
    cost_mode: str = "dynamic",
) -> list[str]:
    issues: set[str] = set()
    timing = specification["timing"]
    anchor_seconds = int(timing["anchor_seconds_after_release"])
    expected_horizons = {
        anchor_seconds,
        *[int(value) for value in timing["exit_seconds_after_release"]],
    }
    max_lag = float(timing["maximum_quote_lag_seconds"])
    if cost_mode != "dynamic":
        issues.add("constant_cost_forbidden")
    if len({event.event_id for event in events}) != len(events):
        issues.add("duplicate_event_id")
    by_event: dict[str, list[dict[str, Any]]] = {}
    for quote in quotes:
        by_event.setdefault(str(quote.get("event_id")), []).append(quote)
        try:
            bid = _finite(quote["bid"])
            ask = _finite(quote["ask"])
            lag = _finite(quote["quote_lag_seconds"])
        except (KeyError, TypeError, ValueError):
            issues.add("nonfinite_numeric_value")
            continue
        if bid <= 0 or ask <= bid:
            issues.add("invalid_bid_ask")
        if abs(lag) > max_lag:
            issues.add("quote_lag_exceeded")
    for event in events:
        scheduled = parse_utc(event.scheduled_at)
        ready = parse_utc(event.feature_ready_at)
        anchor = scheduled + timedelta(seconds=anchor_seconds)
        if ready < scheduled or ready > anchor:
            issues.add("feature_not_point_in_time")
        event_quotes = by_event.get(event.event_id, [])
        observed_horizons = {
            int(quote.get("horizon_seconds", -1)) for quote in event_quotes
        }
        if (
            len(event_quotes) != len(expected_horizons)
            or observed_horizons != expected_horizons
        ):
            issues.add("missing_quote_horizon")
        for quote in event_quotes:
            try:
                horizon = int(quote["horizon_seconds"])
                target = scheduled + timedelta(seconds=horizon)
                timestamp = parse_utc(str(quote["timestamp"]))
                actual_lag = (timestamp - target).total_seconds()
                claimed_lag = float(quote["quote_lag_seconds"])
            except (KeyError, TypeError, ValueError):
                issues.add("quote_timestamp_invalid")
            else:
                if actual_lag < 0 or actual_lag > max_lag or abs(actual_lag - claimed_lag) > 1e-9:
                    issues.add("quote_lag_exceeded")
        if any(not math.isfinite(value) for value in event.features):
            issues.add("nonfinite_numeric_value")
    return sorted(issues)


def build_labels(
    events: list[PriceEvent],
    quotes: list[dict[str, Any]],
    specification: dict[str, Any],
) -> list[dict[str, Any]]:
    issues = validate_pit_inputs(events, quotes, specification)
    if issues:
        raise ValueError(issues[0])
    quote_index = {
        (row["event_id"], int(row["horizon_seconds"])): row for row in quotes
    }
    anchor_seconds = int(specification["timing"]["anchor_seconds_after_release"])
    output: list[dict[str, Any]] = []
    for event in events:
        entry = quote_index[(event.event_id, anchor_seconds)]
        feature_values = dict(zip(FEATURE_NAMES, event.features))
        pre_vol = feature_values["pre_volatility_bp"]
        for horizon in specification["timing"]["exit_seconds_after_release"]:
            exit_quote = quote_index[(event.event_id, int(horizon))]
            target = (exit_quote["mid"] / entry["mid"] - 1.0) * 10_000.0
            entry_slippage = dynamic_slippage_bp(entry["spread_bp"], pre_vol)
            exit_slippage = dynamic_slippage_bp(exit_quote["spread_bp"], pre_vol)
            long_net = (
                (exit_quote["bid"] - entry["ask"]) / entry["mid"] * 10_000.0
                - entry_slippage
                - exit_slippage
            )
            short_net = (
                (entry["bid"] - exit_quote["ask"]) / entry["mid"] * 10_000.0
                - entry_slippage
                - exit_slippage
            )
            output.append(
                {
                    "event_id": event.event_id,
                    "evidence_package_id": event.evidence_package_id,
                    "scheduled_at": event.scheduled_at,
                    "event_family": event.event_family,
                    "feature_ready_at": event.feature_ready_at,
                    "asset": specification["asset"],
                    "dataset_role": event.dataset_role,
                    "provenance": event.provenance,
                    "entry_horizon_seconds": anchor_seconds,
                    "exit_horizon_seconds": int(horizon),
                    **feature_values,
                    "entry_timestamp": entry["timestamp"],
                    "entry_bid": entry["bid"],
                    "entry_ask": entry["ask"],
                    "entry_mid": entry["mid"],
                    "entry_spread_bp": entry["spread_bp"],
                    "exit_timestamp": exit_quote["timestamp"],
                    "exit_bid": exit_quote["bid"],
                    "exit_ask": exit_quote["ask"],
                    "exit_mid": exit_quote["mid"],
                    "exit_spread_bp": exit_quote["spread_bp"],
                    "entry_slippage_bp": entry_slippage,
                    "exit_slippage_bp": exit_slippage,
                    "entry_quote_provenance": entry.get("quote_provenance"),
                    "exit_quote_provenance": exit_quote.get("quote_provenance"),
                    "target_mid_bp": target,
                    "long_net_bp": long_net,
                    "short_net_bp": short_net,
                    "cost_model": "dynamic_spread_volatility_v1",
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def rows_csv_sha256(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise ValueError("cannot hash empty CSV rows")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()
