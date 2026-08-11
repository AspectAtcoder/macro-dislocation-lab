from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import socket
import statistics
import struct
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


UTC = timezone.utc
NTP_EPOCH_DELTA = 2_208_988_800
PLAN_FIELDS = (
    "plan_id",
    "provider_bundle_id",
    "event_family",
    "country",
    "currency",
    "scheduled_at",
    "expected_components",
    "schedule_source_url",
    "schedule_captured_at",
    "schedule_sha256",
    "stream_start_at",
    "pre_snapshot_due_at",
    "stream_end_at",
)
TRACE_FIELDS = (
    "run_id",
    "plan_id",
    "kind",
    "observed_at",
    "received_monotonic_ns",
    "details",
)
TRACE_KINDS = {
    "run_started",
    "clock_sample",
    "stream_connected",
    "heartbeat",
    "pre_snapshot_captured",
    "release_component",
    "stream_disconnected",
    "stream_reconnected",
    "store_audit",
    "stream_closed",
}


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be offset-aware: {value}")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def official_local_to_utc(
    local_date: str, local_time: str, *, timezone_name: str = "America/New_York"
) -> str:
    """Convert an official named-zone schedule without a fixed offset assumption."""
    parsed_date = date.fromisoformat(local_date)
    parsed_time = datetime_time.fromisoformat(local_time)
    local = datetime.combine(parsed_date, parsed_time, ZoneInfo(timezone_name))
    return _iso(local)


@dataclass(frozen=True)
class ReleaseWindowPlan:
    plan_id: str
    provider_bundle_id: str
    event_family: str
    country: str
    currency: str
    scheduled_at: str
    expected_components: list[str]
    schedule_source_url: str
    schedule_captured_at: str
    schedule_sha256: str
    stream_start_at: str
    pre_snapshot_due_at: str
    stream_end_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_release_plans(
    schedule_path: Path, policy: dict[str, Any]
) -> list[ReleaseWindowPlan]:
    payload = schedule_path.read_bytes()
    schedule_hash = _hash_bytes(payload)
    value = json.loads(payload.decode("utf-8"))
    source_url = str(value.get("schedule_source_url") or "")
    if not source_url.startswith("https://"):
        raise ValueError("schedule_source_url must use https")
    captured = _parse_utc(str(value.get("captured_at") or ""))
    bundles = value.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise ValueError("schedule requires a non-empty bundles list")
    plans: list[ReleaseWindowPlan] = []
    seen: set[str] = set()
    for item in bundles:
        if not isinstance(item, dict):
            raise ValueError("schedule bundle must be an object")
        provider_id = str(item.get("provider_bundle_id") or "").strip()
        if not provider_id or provider_id in seen:
            raise ValueError("schedule requires unique provider_bundle_id values")
        seen.add(provider_id)
        scheduled = _parse_utc(str(item.get("scheduled_at") or ""))
        if captured >= scheduled:
            raise ValueError("schedule must be captured before its release")
        if (scheduled - captured).total_seconds() > policy["schedule_max_age_seconds"]:
            raise ValueError("schedule capture is older than the registered maximum")
        components = item.get("expected_components")
        if (
            not isinstance(components, list)
            or not components
            or any(not isinstance(component, str) or not component for component in components)
            or len(set(components)) != len(components)
        ):
            raise ValueError("expected_components must be unique non-empty strings")
        event_family = str(item.get("event_family") or "").upper()
        country = str(item.get("country") or "").strip()
        currency = str(item.get("currency") or "").strip()
        if event_family not in {"CPI", "NFP"}:
            raise ValueError("Phase 4 event_family must be CPI or NFP")
        if not country or not currency:
            raise ValueError("schedule bundle requires country and currency")
        identity = {
            "provider_bundle_id": provider_id,
            "scheduled_at": _iso(scheduled),
            "schedule_sha256": schedule_hash,
        }
        plans.append(
            ReleaseWindowPlan(
                plan_id="shadow:" + _hash_json(identity)[:20],
                provider_bundle_id=provider_id,
                event_family=event_family,
                country=country,
                currency=currency,
                scheduled_at=_iso(scheduled),
                expected_components=sorted(components),
                schedule_source_url=source_url,
                schedule_captured_at=_iso(captured),
                schedule_sha256=schedule_hash,
                stream_start_at=_iso(
                    scheduled - timedelta(seconds=policy["stream_lead_seconds"])
                ),
                pre_snapshot_due_at=_iso(
                    scheduled
                    - timedelta(seconds=policy["pre_snapshot_target_seconds"])
                ),
                stream_end_at=_iso(
                    scheduled + timedelta(seconds=policy["stream_tail_seconds"])
                ),
            )
        )
    return sorted(plans, key=lambda plan: (plan.scheduled_at, plan.plan_id))


def load_trace_fixture(path: Path, plan: ReleaseWindowPlan) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("trace fixture must be a list")
    output: list[dict[str, Any]] = []
    for row in rows:
        item = json.loads(json.dumps(row))
        if item.get("plan_id") == "$PLAN_ID":
            item["plan_id"] = plan.plan_id
        details = item.get("details", {})
        if details.get("schedule_sha256") == "$SCHEDULE_SHA256":
            details["schedule_sha256"] = plan.schedule_sha256
        output.append(normalize_trace_event(item))
    return output


def normalize_trace_event(event: dict[str, Any]) -> dict[str, Any]:
    missing = [name for name in TRACE_FIELDS if name not in event]
    if missing:
        raise ValueError(f"trace event missing fields: {', '.join(missing)}")
    if event["kind"] not in TRACE_KINDS:
        raise ValueError(f"unknown trace event kind: {event['kind']}")
    if not isinstance(event["received_monotonic_ns"], int) or event[
        "received_monotonic_ns"
    ] < 0:
        raise ValueError("received_monotonic_ns must be a non-negative integer")
    if not isinstance(event["details"], dict):
        raise ValueError("trace event details must be an object")
    normalized = dict(event)
    normalized["observed_at"] = _iso(_parse_utc(str(event["observed_at"])))
    normalized["event_id"] = _hash_json(
        {name: normalized[name] for name in TRACE_FIELDS}
    )
    return normalized


def create_trace_event(
    *, run_id: str, plan_id: str, kind: str, details: dict[str, Any]
) -> dict[str, Any]:
    return normalize_trace_event(
        {
            "run_id": run_id,
            "plan_id": plan_id,
            "kind": kind,
            "observed_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            "received_monotonic_ns": time.monotonic_ns(),
            "details": details,
        }
    )


class ShadowTraceStore:
    """Append-only run telemetry used by the operational campaign audit."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "trace.jsonl"
        root.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_trace_event(event)
        line = (
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            written = 0
            while written < len(line):
                written += os.write(descriptor, line[written:])
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return normalized

    def events(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        output: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise ValueError(f"torn trace line: {line_number}")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid trace JSON: {line_number}") from exc
                normalized = normalize_trace_event(row)
                if normalized["event_id"] != row.get("event_id"):
                    raise ValueError(f"trace event hash mismatch: {line_number}")
                output.append(normalized)
        return output


def _event_times(events: Iterable[dict[str, Any]], kind: str) -> list[datetime]:
    return [_parse_utc(event["observed_at"]) for event in events if event["kind"] == kind]


def audit_shadow_trace(
    plan: ReleaseWindowPlan,
    events: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    issues: set[str] = set()
    if not events:
        raise ValueError("shadow trace requires at least one event")
    normalized = [normalize_trace_event(event) for event in events]
    if len({event["run_id"] for event in normalized}) != 1:
        issues.add("multiple_run_ids")
    if any(event["plan_id"] != plan.plan_id for event in normalized):
        issues.add("plan_id_mismatch")
    wall_times = [_parse_utc(event["observed_at"]) for event in normalized]
    monotonic = [event["received_monotonic_ns"] for event in normalized]
    if wall_times != sorted(wall_times) or monotonic != sorted(monotonic):
        issues.add("trace_order_violation")
    if len({event["event_id"] for event in normalized}) != len(normalized):
        issues.add("duplicate_trace_event")

    run_started = [event for event in normalized if event["kind"] == "run_started"]
    if len(run_started) != 1 or run_started[0]["details"].get(
        "schedule_sha256"
    ) != plan.schedule_sha256:
        issues.add("schedule_hash_mismatch")

    scheduled = _parse_utc(plan.scheduled_at)
    stream_start = _parse_utc(plan.stream_start_at)
    stream_end = _parse_utc(plan.stream_end_at)
    clock_events = [event for event in normalized if event["kind"] == "clock_sample"]
    valid_clock_events = [
        event
        for event in clock_events
        if stream_start - timedelta(seconds=60)
        <= _parse_utc(event["observed_at"])
        < scheduled
    ]
    if len(valid_clock_events) < policy["minimum_clock_samples"]:
        issues.add("insufficient_clock_samples")
    if len(
        {
            str(event["details"].get("server") or "")
            for event in valid_clock_events
            if event["details"].get("server")
        }
    ) < policy["minimum_clock_samples"]:
        issues.add("insufficient_independent_clock_sources")
    offsets = [
        abs(float(event["details"].get("offset_ms", float("inf"))))
        for event in valid_clock_events
    ]
    rtts = [
        float(event["details"].get("rtt_ms", float("inf")))
        for event in valid_clock_events
    ]
    median_offset = statistics.median(offsets) if offsets else None
    max_rtt = max(rtts) if rtts else None
    if (
        median_offset is None
        or not math.isfinite(median_offset)
        or median_offset > policy["maximum_clock_offset_ms"]
    ):
        issues.add("clock_offset_exceeded")
    if (
        max_rtt is None
        or not math.isfinite(max_rtt)
        or max_rtt < 0
        or max_rtt > policy["maximum_clock_rtt_ms"]
    ):
        issues.add("clock_rtt_exceeded")

    connected = _event_times(normalized, "stream_connected")
    if not connected:
        issues.add("missing_stream_connection")
    elif min(connected) > stream_start:
        issues.add("late_stream_connection")

    pre_events = [event for event in normalized if event["kind"] == "pre_snapshot_captured"]
    valid_pre = [
        event
        for event in pre_events
        if 0
        < (scheduled - _parse_utc(event["observed_at"])).total_seconds()
        <= policy["pre_snapshot_max_age_seconds"]
        and set(event["details"].get("consensus_components", []))
        >= set(plan.expected_components)
    ]
    if not valid_pre:
        issues.add("missing_pre_release_snapshot")

    release_events = [event for event in normalized if event["kind"] == "release_component"]
    valid_components: set[str] = set()
    component_latencies: dict[str, float] = {}
    for event in release_events:
        received = _parse_utc(event["observed_at"])
        component = str(event["details"].get("component_id") or "")
        latency = (received - scheduled).total_seconds()
        if latency < 0:
            issues.add("release_before_scheduled")
        elif latency <= policy["component_completion_seconds"]:
            valid_components.add(component)
            component_latencies[component] = latency
    if not set(plan.expected_components).issubset(valid_components):
        issues.add("missing_release_component")

    disconnected = _event_times(normalized, "stream_disconnected")
    reconnected = _event_times(normalized, "stream_reconnected")
    reconnect_gaps: list[float] = []
    if len(disconnected) != len(reconnected):
        issues.add("unpaired_reconnect")
    for left, right in zip(disconnected, reconnected):
        gap = (right - left).total_seconds()
        reconnect_gaps.append(gap)
        if gap < 0 or gap > policy["maximum_reconnect_gap_seconds"]:
            issues.add("reconnect_gap_exceeded")

    telemetry_kinds = {
        "stream_connected",
        "heartbeat",
        "pre_snapshot_captured",
        "release_component",
        "stream_disconnected",
        "stream_reconnected",
        "store_audit",
        "stream_closed",
    }
    telemetry = [
        _parse_utc(event["observed_at"])
        for event in normalized
        if event["kind"] in telemetry_kinds
    ]
    telemetry_gaps = [
        (right - left).total_seconds() for left, right in zip(telemetry, telemetry[1:])
    ]
    max_telemetry_gap = max(telemetry_gaps, default=None)
    if (
        max_telemetry_gap is None
        or max_telemetry_gap > policy["maximum_telemetry_gap_seconds"]
    ):
        issues.add("telemetry_gap_exceeded")

    store_events = [event for event in normalized if event["kind"] == "store_audit"]
    if not store_events or store_events[-1]["details"].get("passed") is not True:
        issues.add("raw_store_integrity_failed")
    closed = _event_times(normalized, "stream_closed")
    if not closed or max(closed) < stream_end:
        issues.add("stream_closed_before_window_end")
    if store_events and closed and _parse_utc(store_events[-1]["observed_at"]) > max(closed):
        issues.add("store_audit_after_stream_close")

    provenance = (
        str(run_started[0]["details"].get("provenance") or "")
        if run_started
        else ""
    )
    operationally_complete = not issues
    empirical_window = operationally_complete and provenance == "licensed_shadow"
    pre_lead = (
        (scheduled - _parse_utc(valid_pre[-1]["observed_at"])).total_seconds()
        if valid_pre
        else None
    )
    audit = {
        "run_id": normalized[0]["run_id"],
        "plan_id": plan.plan_id,
        "event_family": plan.event_family,
        "scheduled_at": plan.scheduled_at,
        "trace_events": len(normalized),
        "operationally_complete": operationally_complete,
        "empirical_window": empirical_window,
        "provenance": provenance,
        "issues": sorted(issues),
        "metrics": {
            "clock_samples": len(valid_clock_events),
            "median_absolute_clock_offset_ms": median_offset,
            "maximum_clock_rtt_ms": max_rtt,
            "pre_snapshot_lead_seconds": pre_lead,
            "release_component_latencies_seconds": component_latencies,
            "reconnects": len(reconnected),
            "reconnect_gaps_seconds": reconnect_gaps,
            "maximum_telemetry_gap_seconds": max_telemetry_gap,
        },
    }
    audit["audit_hash"] = shadow_audit_hash(audit)
    return audit


def shadow_audit_hash(audit: dict[str, Any]) -> str:
    return _hash_json({key: value for key, value in audit.items() if key != "audit_hash"})


def campaign_promotion_gate(
    audits: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    duplicate_run_ids: list[str] = []
    for audit in audits:
        run_id = str(audit["run_id"])
        if run_id in unique:
            duplicate_run_ids.append(run_id)
        else:
            unique[run_id] = audit
    complete = [
        audit
        for audit in unique.values()
        if audit.get("operationally_complete") is True
        and audit.get("empirical_window") is True
        and audit.get("provenance") == "licensed_shadow"
        and audit.get("issues") == []
        and audit.get("audit_hash") == shadow_audit_hash(audit)
    ]
    duplicate_plan_ids: list[str] = []
    duplicate_release_windows: list[str] = []
    seen_plans: set[str] = set()
    seen_releases: set[tuple[str, str]] = set()
    empirical: list[dict[str, Any]] = []
    for audit in complete:
        plan_id = str(audit.get("plan_id") or "")
        release_key = (
            str(audit.get("event_family") or "").upper(),
            str(audit.get("scheduled_at") or ""),
        )
        if plan_id in seen_plans:
            duplicate_plan_ids.append(plan_id)
            continue
        if release_key in seen_releases:
            duplicate_release_windows.append("|".join(release_key))
            continue
        seen_plans.add(plan_id)
        seen_releases.add(release_key)
        empirical.append(audit)
    cpi = sum(str(audit.get("event_family")).upper() == "CPI" for audit in empirical)
    nfp = sum(str(audit.get("event_family")).upper() == "NFP" for audit in empirical)
    reasons: list[str] = []
    if duplicate_run_ids:
        reasons.append("duplicate_run_id")
    if duplicate_plan_ids:
        reasons.append("duplicate_plan_id")
    if duplicate_release_windows:
        reasons.append("duplicate_release_window")
    invalid_audits = [
        str(audit.get("run_id") or "")
        for audit in unique.values()
        if audit.get("operationally_complete") is True
        and audit.get("empirical_window") is True
        and (
            audit.get("provenance") != "licensed_shadow"
            or audit.get("issues") != []
            or audit.get("audit_hash") != shadow_audit_hash(audit)
        )
    ]
    if invalid_audits:
        reasons.append("invalid_empirical_audit")
    if len(empirical) < policy["minimum_complete_windows"]:
        reasons.append("insufficient_complete_windows")
    if cpi < policy["minimum_complete_cpi_windows"]:
        reasons.append("insufficient_cpi_windows")
    if nfp < policy["minimum_complete_nfp_windows"]:
        reasons.append("insufficient_nfp_windows")
    result = {
        "promoted": not reasons,
        "complete_empirical_windows": len(empirical),
        "complete_cpi_windows": cpi,
        "complete_nfp_windows": nfp,
        "duplicate_run_ids": sorted(set(duplicate_run_ids)),
        "duplicate_plan_ids": sorted(set(duplicate_plan_ids)),
        "duplicate_release_windows": sorted(set(duplicate_release_windows)),
        "invalid_empirical_audits": sorted(set(invalid_audits)),
        "reasons": reasons,
    }
    result["campaign_hash"] = _hash_json(result)
    return result


def _ntp_time(packet: bytes, offset: int) -> float:
    seconds, fraction = struct.unpack("!II", packet[offset : offset + 8])
    return seconds - NTP_EPOCH_DELTA + fraction / 2**32


def query_ntp_clock_sample(
    server: str,
    *,
    run_id: str,
    plan_id: str,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Collect one unauthenticated NTP diagnostic sample for a shadow trace."""
    if not server or any(character.isspace() for character in server):
        raise ValueError("invalid NTP server name")
    request = bytearray(48)
    request[0] = 0x23
    started_unix = time.time()
    started_monotonic = time.monotonic_ns()
    ntp_started = started_unix + NTP_EPOCH_DELTA
    seconds = int(ntp_started)
    fraction = int((ntp_started - seconds) * 2**32)
    request[40:48] = struct.pack("!II", seconds, fraction)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.settimeout(timeout)
        connection.sendto(request, (server, 123))
        response, _ = connection.recvfrom(512)
    received_unix = time.time()
    received_monotonic = time.monotonic_ns()
    if len(response) < 48 or response[1] == 0 or (response[0] & 0x07) != 4:
        raise ValueError("invalid NTP server response")
    if response[24:32] != request[40:48]:
        raise ValueError("NTP originate timestamp does not match the request")
    server_received = _ntp_time(response, 32)
    server_transmitted = _ntp_time(response, 40)
    offset_seconds = (
        (server_received - started_unix) + (server_transmitted - received_unix)
    ) / 2
    local_elapsed_seconds = (received_monotonic - started_monotonic) / 1_000_000_000
    rtt_seconds = local_elapsed_seconds - (
        server_transmitted - server_received
    )
    return normalize_trace_event(
        {
            "run_id": run_id,
            "plan_id": plan_id,
            "kind": "clock_sample",
            "observed_at": datetime.fromtimestamp(received_unix, UTC).isoformat(),
            "received_monotonic_ns": received_monotonic,
            "details": {
                "server": server,
                "offset_ms": offset_seconds * 1000,
                "rtt_ms": max(rtt_seconds, 0.0) * 1000,
                "request_monotonic_ns": started_monotonic,
                "protocol": "NTPv4-unauthenticated-diagnostic",
            },
        }
    )
