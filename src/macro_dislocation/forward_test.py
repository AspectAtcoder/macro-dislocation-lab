from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .pit_prices import dynamic_slippage_bp
from .walk_forward import predict_model


UTC = timezone.utc
GENESIS_HASH = "0" * 64
OUTCOME_FIELDS = {
    "target_mid_bp",
    "exit_bid",
    "exit_ask",
    "exit_mid",
    "net_return_bp",
    "direction_correct",
}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("forward timestamp must be offset-aware")
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def forward_event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({key: value for key, value in event.items() if key != "event_hash"})
    ).hexdigest()


def seal_forward_event(event: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(event)
    sealed["event_hash"] = forward_event_hash(sealed)
    return sealed


def replay_forward_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    issues: set[str] = set()
    previous_hash = GENESIS_HASH
    open_signals: dict[str, dict[str, Any]] = {}
    settled: set[str] = set()
    signals = 0
    settlements = 0
    for sequence, event in enumerate(events, start=1):
        if event.get("sequence") != sequence:
            issues.add("forward_sequence_mismatch")
        if event.get("previous_hash") != previous_hash:
            issues.add("forward_hash_chain_mismatch")
        if event.get("event_hash") != forward_event_hash(event):
            issues.add("forward_event_hash_mismatch")
        previous_hash = str(event.get("event_hash") or "")
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            issues.add("forward_payload_invalid")
            continue
        signal_id = str(payload.get("signal_id") or "")
        if event_type == "SIGNAL":
            signals += 1
            if any(name in payload for name in OUTCOME_FIELDS):
                issues.add("forward_outcome_leakage")
            if not signal_id or signal_id in open_signals or signal_id in settled:
                issues.add("forward_duplicate_signal")
            if not str(payload.get("evidence_package_id") or "").strip():
                issues.add("missing_evidence_package_id")
            open_signals[signal_id] = event
        elif event_type == "SETTLEMENT":
            settlements += 1
            signal = open_signals.get(signal_id)
            if signal is None:
                issues.add("forward_signal_not_open")
            else:
                signal_payload = signal["payload"]
                if (
                    payload.get("event_id") != signal_payload.get("event_id")
                    or payload.get("evidence_package_id")
                    != signal_payload.get("evidence_package_id")
                ):
                    issues.add("forward_settlement_identity_mismatch")
                due = parse_utc(str(signal["payload"]["exit_due_at"]))
                occurred = parse_utc(str(event["occurred_at"]))
                if occurred < due:
                    issues.add("forward_settlement_too_early")
                del open_signals[signal_id]
                settled.add(signal_id)
        else:
            issues.add("forward_event_type_invalid")
    return {
        "passed": not issues,
        "issues": sorted(issues),
        "events": len(events),
        "signals": signals,
        "settlements": settlements,
        "open_signals": len(open_signals),
        "head_hash": previous_hash,
    }


def risk_issues(
    *,
    now: str,
    quote_timestamp: str,
    bid: float,
    ask: float,
    open_positions: int,
    daily_pnl_bp: float,
    kill_switch: bool,
    policy: dict[str, Any],
) -> list[str]:
    issues: set[str] = set()
    current = parse_utc(now)
    quote_time = parse_utc(quote_timestamp)
    age = (current - quote_time).total_seconds()
    if kill_switch:
        issues.add("kill_switch_active")
    if age < 0 or age > float(policy["maximum_quote_age_seconds"]):
        issues.add("forward_quote_stale")
    if not all(math.isfinite(value) for value in (bid, ask)) or bid <= 0 or ask <= bid:
        issues.add("forward_quote_invalid")
    else:
        spread_bp = (ask - bid) / ((ask + bid) / 2.0) * 10_000.0
        if spread_bp > float(policy["maximum_spread_bp"]):
            issues.add("forward_spread_too_wide")
    if open_positions >= int(policy["maximum_open_positions"]):
        issues.add("forward_position_limit")
    if daily_pnl_bp <= -float(policy["daily_loss_limit_bp"]):
        issues.add("daily_loss_limit_reached")
    return sorted(issues)


def journal_risk_state(events: list[dict[str, Any]], now: str) -> dict[str, Any]:
    current_date = parse_utc(now).date()
    signals = {
        event["payload"]["signal_id"]: event
        for event in events
        if event.get("event_type") == "SIGNAL"
    }
    settlements = {
        event["payload"]["signal_id"]: event
        for event in events
        if event.get("event_type") == "SETTLEMENT"
    }
    open_positions = sum(
        int(event["payload"]["position"] != 0)
        for signal_id, event in signals.items()
        if signal_id not in settlements
    )
    daily_pnl = sum(
        float(event["payload"]["net_return_bp"])
        for event in settlements.values()
        if parse_utc(event["occurred_at"]).date() == current_date
    )
    return {"open_positions": open_positions, "daily_pnl_bp": daily_pnl}


class ForwardJournal:
    def __init__(self, path: Path):
        self.path = path

    def events(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as handle:
            lines = list(handle)
        if lines and not lines[-1].endswith("\n"):
            raise ValueError("torn forward journal line")
        return [json.loads(line) for line in lines]

    def append(
        self,
        event_type: str,
        occurred_at: str,
        payload: dict[str, Any],
        provenance: str,
        *,
        validate_current: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            if raw and not raw.endswith(b"\n"):
                raise ValueError("torn forward journal line")
            current = [json.loads(line) for line in raw.splitlines() if line]
            current_audit = replay_forward_events(current)
            if not current_audit["passed"]:
                raise ValueError(current_audit["issues"][0])
            if validate_current is not None:
                validate_current(current)
            previous = current[-1]["event_hash"] if current else GENESIS_HASH
            event = seal_forward_event(
                {
                    "sequence": len(current) + 1,
                    "event_type": event_type,
                    "occurred_at": parse_utc(occurred_at).isoformat(),
                    "payload": payload,
                    "provenance": provenance,
                    "previous_hash": previous,
                }
            )
            audit = replay_forward_events([*current, event])
            if not audit["passed"]:
                raise ValueError(audit["issues"][0])
            line = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            os.lseek(descriptor, 0, os.SEEK_END)
            written = 0
            while written < len(line):
                written += os.write(descriptor, line[written:])
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return event


def record_paper_signal(
    journal: ForwardJournal,
    model: dict[str, Any],
    signal_input: dict[str, Any],
    *,
    now: str,
    policy: dict[str, Any],
    kill_switch: bool,
    trade_threshold_bp: float,
) -> dict[str, Any]:
    if any(name in signal_input for name in OUTCOME_FIELDS):
        raise ValueError("forward_outcome_leakage")
    if not str(signal_input.get("evidence_package_id") or "").strip():
        raise ValueError("missing_evidence_package_id")
    current = parse_utc(now)
    if parse_utc(str(signal_input["feature_ready_at"])) > current:
        raise ValueError("feature_not_point_in_time")
    if parse_utc(str(signal_input["exit_timestamp"])) <= current:
        raise ValueError("forward_exit_not_future")
    bid = float(signal_input["entry_bid"])
    ask = float(signal_input["entry_ask"])
    forecast = predict_model(model, signal_input)
    position = 1 if forecast >= trade_threshold_bp else -1 if forecast <= -trade_threshold_bp else 0
    identity = {
        "event_id": signal_input["event_id"],
        "evidence_package_id": signal_input["evidence_package_id"],
        "model_hash": model["model_hash"],
        "entry_timestamp": signal_input["entry_timestamp"],
    }
    signal_id = "signal:" + hashlib.sha256(_canonical(identity)).hexdigest()[:32]
    entry_mid = (bid + ask) / 2.0
    spread_bp = (ask - bid) / entry_mid * 10_000.0
    payload = {
        "signal_id": signal_id,
        "event_id": signal_input["event_id"],
        "evidence_package_id": signal_input["evidence_package_id"],
        "event_family": signal_input["event_family"],
        "scheduled_at": signal_input["scheduled_at"],
        "feature_ready_at": signal_input["feature_ready_at"],
        "model_hash": model["model_hash"],
        "features": {name: float(signal_input[name]) for name in model["features"]},
        "forecast_target_bp": forecast,
        "position": position,
        "entry_timestamp": signal_input["entry_timestamp"],
        "entry_bid": bid,
        "entry_ask": ask,
        "entry_mid": entry_mid,
        "entry_spread_bp": spread_bp,
        "entry_slippage_bp": dynamic_slippage_bp(spread_bp, float(signal_input["pre_volatility_bp"])),
        "pre_volatility_bp": float(signal_input["pre_volatility_bp"]),
        "exit_due_at": signal_input["exit_timestamp"],
        "mode": "paper_only",
    }
    def validate_current(events: list[dict[str, Any]]) -> None:
        state = journal_risk_state(events, now)
        issues = risk_issues(
            now=now,
            quote_timestamp=str(signal_input["entry_timestamp"]),
            bid=bid,
            ask=ask,
            open_positions=state["open_positions"],
            daily_pnl_bp=state["daily_pnl_bp"],
            kill_switch=kill_switch,
            policy=policy,
        )
        if issues:
            raise ValueError(issues[0])

    return journal.append(
        "SIGNAL",
        now,
        payload,
        str(signal_input["provenance"]),
        validate_current=validate_current,
    )


def settle_paper_signal(
    journal: ForwardJournal,
    signal_id: str,
    *,
    occurred_at: str,
    exit_bid: float,
    exit_ask: float,
    provenance: str,
) -> dict[str, Any]:
    events = journal.events()
    signals = {
        event["payload"]["signal_id"]: event
        for event in events
        if event["event_type"] == "SIGNAL"
    }
    settled = {
        event["payload"]["signal_id"]
        for event in events
        if event["event_type"] == "SETTLEMENT"
    }
    if signal_id not in signals or signal_id in settled:
        raise ValueError("forward_signal_not_open")
    signal = signals[signal_id]["payload"]
    if parse_utc(occurred_at) < parse_utc(signal["exit_due_at"]):
        raise ValueError("forward_settlement_too_early")
    if exit_bid <= 0 or exit_ask <= exit_bid:
        raise ValueError("forward_quote_invalid")
    exit_mid = (exit_bid + exit_ask) / 2.0
    exit_spread_bp = (exit_ask - exit_bid) / exit_mid * 10_000.0
    exit_slippage = dynamic_slippage_bp(exit_spread_bp, signal["pre_volatility_bp"])
    position = int(signal["position"])
    if position > 0:
        net = (
            (exit_bid - signal["entry_ask"]) / signal["entry_mid"] * 10_000.0
            - signal["entry_slippage_bp"]
            - exit_slippage
        )
    elif position < 0:
        net = (
            (signal["entry_bid"] - exit_ask) / signal["entry_mid"] * 10_000.0
            - signal["entry_slippage_bp"]
            - exit_slippage
        )
    else:
        net = 0.0
    target = (exit_mid / signal["entry_mid"] - 1.0) * 10_000.0
    payload = {
        "signal_id": signal_id,
        "event_id": signal["event_id"],
        "evidence_package_id": signal["evidence_package_id"],
        "target_mid_bp": target,
        "exit_bid": exit_bid,
        "exit_ask": exit_ask,
        "exit_mid": exit_mid,
        "exit_spread_bp": exit_spread_bp,
        "exit_slippage_bp": exit_slippage,
        "net_return_bp": net,
        "direction_correct": int(position != 0 and (position > 0) == (target > 0)),
        "mode": "paper_only",
    }
    return journal.append("SETTLEMENT", occurred_at, payload, provenance)
