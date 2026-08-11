from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
ROSTER_FIELDS = ("roster_id", "checked_at", "official_timezone", "sources", "events")
ROSTER_EVENT_FIELDS = (
    "source_event_id",
    "event_family",
    "reference_month",
    "release_local_date",
    "release_local_time",
    "expected_logical_components",
)


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
    return value.isoformat()


def _local_release(
    local_date: str, local_time: str, timezone_name: str
) -> datetime:
    return datetime.combine(
        date.fromisoformat(local_date),
        datetime_time.fromisoformat(local_time),
        ZoneInfo(timezone_name),
    )


@dataclass(frozen=True)
class CampaignWindow:
    source_event_id: str
    event_family: str
    reference_month: str
    release_local_date: str
    release_local_time: str
    expected_logical_components: list[str]
    schedule_source_url: str
    scheduled_at: str
    operator_at: str
    schedule_refresh_after: str
    access_ready_by: str
    rehearsal_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CampaignRoster:
    roster_id: str
    checked_at: str
    official_timezone: str
    roster_sha256: str
    windows: list[CampaignWindow]
    audit_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "roster_id": self.roster_id,
            "checked_at": self.checked_at,
            "official_timezone": self.official_timezone,
            "roster_sha256": self.roster_sha256,
            "windows": [window.to_dict() for window in self.windows],
            "audit_hash": self.audit_hash,
        }


def audit_roster_payload(
    payload: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    issues: set[str] = set()
    missing_roster = [name for name in ROSTER_FIELDS if name not in payload]
    if missing_roster:
        return {
            "passed": False,
            "issues": ["roster_schema_mismatch"],
            "campaign_windows": 0,
            "cpi_windows": 0,
            "nfp_windows": 0,
            "audit_hash": _hash_json(payload),
        }
    timezone_name = str(payload.get("official_timezone") or "")
    if timezone_name != "America/New_York":
        issues.add("utc_conversion_mismatch")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        issues.add("utc_conversion_mismatch")
        zone = ZoneInfo("UTC")
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        issues.add("roster_schema_mismatch")
    trusted_hosts = set(policy["trusted_source_hosts"])
    for family in ("CPI", "NFP"):
        url = str(sources.get(family) or "")
        parsed = urlsplit(url)
        expected_path = "cpi.htm" if family == "CPI" else "empsit.htm"
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() not in trusted_hosts
            or not parsed.path.endswith(expected_path)
        ):
            issues.add("untrusted_schedule_source")
    events = payload.get("events")
    if not isinstance(events, list):
        events = []
        issues.add("roster_schema_mismatch")
    source_ids: set[str] = set()
    release_keys: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict) or any(
            name not in item for name in ROSTER_EVENT_FIELDS
        ):
            issues.add("roster_event_schema_mismatch")
            continue
        source_id = str(item.get("source_event_id") or "")
        family = str(item.get("event_family") or "").upper()
        release_date = str(item.get("release_local_date") or "")
        components = item.get("expected_logical_components")
        if source_id in source_ids or (family, release_date) in release_keys:
            issues.add("duplicate_release_window")
        source_ids.add(source_id)
        release_keys.add((family, release_date))
        if family not in {"CPI", "NFP"}:
            issues.add("unknown_event_family")
        if (
            not isinstance(components, list)
            or not components
            or any(not isinstance(value, str) or not value for value in components)
            or len(set(components)) != len(components)
        ):
            issues.add("invalid_logical_components")
        try:
            local = datetime.combine(
                date.fromisoformat(release_date),
                datetime_time.fromisoformat(str(item.get("release_local_time") or "")),
                zone,
            )
            utc = local.astimezone(UTC)
        except ValueError:
            issues.add("invalid_release_timestamp")
            continue
        normalized.append(
            {
                "source_event_id": source_id,
                "event_family": family,
                "scheduled_at": _iso(utc),
            }
        )
    scheduled = [item["scheduled_at"] for item in normalized]
    if scheduled != sorted(scheduled):
        issues.add("roster_not_chronological")
    cpi = sum(item["event_family"] == "CPI" for item in normalized)
    nfp = sum(item["event_family"] == "NFP" for item in normalized)
    if (
        len(normalized) < policy["minimum_campaign_windows"]
        or cpi < policy["minimum_cpi_windows"]
        or nfp < policy["minimum_nfp_windows"]
    ):
        issues.add("family_floor_not_met")
    audit = {
        "passed": not issues,
        "issues": sorted(issues),
        "campaign_windows": len(normalized),
        "cpi_windows": cpi,
        "nfp_windows": nfp,
        "normalized_releases": normalized,
    }
    audit["audit_hash"] = _hash_json(audit)
    return audit


def load_campaign_roster(path: Path, policy: dict[str, Any]) -> CampaignRoster:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    audit = audit_roster_payload(payload, policy)
    if not audit["passed"]:
        raise ValueError(f"invalid campaign roster: {audit['issues'][0]}")
    checked = _parse_utc(str(payload["checked_at"]))
    timezone_name = str(payload["official_timezone"])
    operator_zone = ZoneInfo(policy["operator_timezone"])
    windows: list[CampaignWindow] = []
    for item in payload["events"]:
        local = _local_release(
            str(item["release_local_date"]),
            str(item["release_local_time"]),
            timezone_name,
        )
        scheduled = local.astimezone(UTC)
        family = str(item["event_family"]).upper()
        windows.append(
            CampaignWindow(
                source_event_id=str(item["source_event_id"]),
                event_family=family,
                reference_month=str(item["reference_month"]),
                release_local_date=str(item["release_local_date"]),
                release_local_time=str(item["release_local_time"]),
                expected_logical_components=sorted(
                    str(value) for value in item["expected_logical_components"]
                ),
                schedule_source_url=str(payload["sources"][family]),
                scheduled_at=_iso(scheduled),
                operator_at=_iso(scheduled.astimezone(operator_zone)),
                schedule_refresh_after=_iso(
                    scheduled
                    - timedelta(seconds=policy["schedule_refresh_window_seconds"])
                ),
                access_ready_by=_iso(
                    scheduled
                    - timedelta(seconds=policy["access_ready_lead_seconds"])
                ),
                rehearsal_at=_iso(
                    scheduled - timedelta(seconds=policy["rehearsal_lead_seconds"])
                ),
            )
        )
    windows.sort(key=lambda item: (item.scheduled_at, item.source_event_id))
    return CampaignRoster(
        roster_id=str(payload["roster_id"]),
        checked_at=_iso(checked),
        official_timezone=timezone_name,
        roster_sha256=_hash_bytes(raw),
        windows=windows,
        audit_hash=str(audit["audit_hash"]),
    )


def activation_packet(
    roster: CampaignRoster,
    window: CampaignWindow,
    evaluated_at: str,
    preflight: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    now = _parse_utc(evaluated_at)
    checked = _parse_utc(roster.checked_at)
    scheduled = _parse_utc(window.scheduled_at)
    refresh_after = _parse_utc(window.schedule_refresh_after)
    access_ready_by = _parse_utc(window.access_ready_by)
    issues: list[str] = []
    if now >= scheduled:
        status = "EXPIRED"
        issues.append("release_window_expired")
    elif checked < refresh_after or checked > now:
        status = "BLOCKED_SCHEDULE_REFRESH"
        issues.append("schedule_refresh_required")
    elif now > access_ready_by:
        status = "BLOCKED_ACCESS_DEADLINE_MISSED"
        issues.append("access_deadline_missed")
    elif preflight.get("ready") is not True:
        status = "BLOCKED_VENDOR_ACCESS"
        issues.extend(str(value) for value in preflight.get("issues", []))
    else:
        status = "READY_FOR_ACTIVATION"
    packet = {
        "roster_id": roster.roster_id,
        "roster_sha256": roster.roster_sha256,
        "source_event_id": window.source_event_id,
        "event_family": window.event_family,
        "reference_month": window.reference_month,
        "scheduled_at": window.scheduled_at,
        "operator_at": window.operator_at,
        "schedule_source_url": window.schedule_source_url,
        "schedule_checked_at": roster.checked_at,
        "schedule_refresh_after": window.schedule_refresh_after,
        "access_ready_by": window.access_ready_by,
        "rehearsal_at": window.rehearsal_at,
        "expected_logical_components": window.expected_logical_components,
        "provider_component_ids_resolved": False,
        "evaluated_at": _iso(now),
        "schedule_fresh": refresh_after <= checked <= now,
        "seconds_to_release": int((scheduled - now).total_seconds()),
        "seconds_to_access_deadline": int((access_ready_by - now).total_seconds()),
        "activation_status": status,
        "issues": sorted(set(issues)),
    }
    packet["packet_hash"] = _hash_json(packet)
    return packet


def campaign_readiness(
    roster: CampaignRoster,
    evaluated_at: str,
    preflight: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    now = _parse_utc(evaluated_at)
    upcoming = [
        window for window in roster.windows if _parse_utc(window.scheduled_at) > now
    ]
    expired = [
        window for window in roster.windows if _parse_utc(window.scheduled_at) <= now
    ]
    candidates = [
        window
        for window in upcoming
        if _parse_utc(window.schedule_refresh_after) <= now
    ]
    next_window = upcoming[0] if upcoming else None
    packet = (
        activation_packet(roster, next_window, evaluated_at, preflight, policy)
        if next_window is not None
        else None
    )
    result = {
        "roster_id": roster.roster_id,
        "roster_sha256": roster.roster_sha256,
        "evaluated_at": _iso(now),
        "campaign_windows": len(roster.windows),
        "cpi_windows": sum(window.event_family == "CPI" for window in roster.windows),
        "nfp_windows": sum(window.event_family == "NFP" for window in roster.windows),
        "upcoming_windows": len(upcoming),
        "expired_windows": len(expired),
        "activation_candidates": len(candidates),
        "next_window": next_window.to_dict() if next_window else None,
        "activation_packet": packet,
    }
    result["readiness_hash"] = _hash_json(result)
    return result
