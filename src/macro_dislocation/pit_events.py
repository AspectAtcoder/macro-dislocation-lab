from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .calendar_data import parse_number


UTC = timezone.utc
RIGHTS = ("retention", "historical_backtesting", "machine_learning", "derived_data")


@dataclass(frozen=True)
class PitSnapshot:
    provider: str
    provider_event_id: str
    event_type: str
    component: str
    country: str
    currency: str
    scheduled_at: str
    reference_period: str
    unit: str
    snapshot_at: str | None
    received_at: str | None
    actual: float | None
    consensus: float | None
    previous: float | None
    revised: float | None
    source_url: str
    license_class: str
    rights_profile: dict[str, bool]
    payload_sha256: str
    provenance: str
    provider_updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["rights_profile"] = json.dumps(
            self.rights_profile, sort_keys=True, separators=(",", ":")
        )
        return value


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_aware(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be offset-aware: {value}")
    return parsed.astimezone(UTC)


def _utc_iso(value: str | None) -> str | None:
    parsed = _parse_aware(value)
    return parsed.isoformat() if parsed else None


RESEARCH_COMPONENTS = {
    "CPI": [
        ("cpi_mom", "pct"),
        ("core_cpi_mom", "pct"),
    ],
    "NFP": [
        ("nfp_change", "k"),
        ("unemployment_rate", "pct"),
        ("average_hourly_earnings_mom", "pct"),
    ],
}


def load_research_calendar(path: Path) -> list[PitSnapshot]:
    """Flatten the final research calendar without inventing a vintage timestamp."""
    snapshots: list[PitSnapshot] = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        event_type = row["event_type"]
        for component, suffix in RESEARCH_COMPONENTS[event_type]:
            actual = parse_number(row.get(f"{component}_actual_{suffix}", ""))
            consensus = parse_number(row.get(f"{component}_forecast_{suffix}", ""))
            previous = parse_number(row.get(f"{component}_previous_{suffix}", ""))
            payload = {
                "event_id": row["event_id"],
                "component": component,
                "actual": actual,
                "consensus": consensus,
                "previous": previous,
                "quality_flags": row.get("quality_flags", ""),
            }
            snapshots.append(
                PitSnapshot(
                    provider="research_calendar",
                    provider_event_id=f"{row['event_id']}:{component}",
                    event_type=event_type,
                    component=component,
                    country="United States",
                    currency="USD",
                    scheduled_at=_utc_iso(row["release_timestamp_utc"]) or "",
                    reference_period=row["reference_period"],
                    unit="thousand persons" if suffix == "k" else "percent",
                    snapshot_at=None,
                    received_at=None,
                    actual=actual,
                    consensus=consensus,
                    previous=previous,
                    revised=None,
                    source_url=row.get("consensus_source_url", ""),
                    license_class="research_only_unknown_rights",
                    rights_profile={name: False for name in RIGHTS},
                    payload_sha256=_hash_json(payload),
                    provenance="final_cache_no_vintage",
                )
            )
    return snapshots


def _te_datetime(value: str, *, assume_timezone: timezone = UTC) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=assume_timezone)
    return parsed.astimezone(UTC).isoformat()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _te_get(row: dict[str, Any], *names: str) -> Any:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        if name.strip().lower() in normalized:
            return normalized[name.strip().lower()]
    return None


def normalize_trading_economics_snapshot(
    rows: Iterable[dict[str, Any]],
    *,
    snapshot_at: str,
    received_at: str,
    rights_profile: dict[str, bool],
    license_class: str,
    provenance: str = "captured_api_snapshot",
) -> list[PitSnapshot]:
    """Normalize captured TE snapshot or stream rows through one field mapper."""
    capture_time = _utc_iso(snapshot_at)
    receive_time = _utc_iso(received_at)
    output: list[PitSnapshot] = []
    for row in rows:
        provider_id = str(_te_get(row, "CalendarId") or "").strip()
        if not provider_id:
            raise ValueError("Trading Economics row missing CalendarId")
        event_name = str(_te_get(row, "Event", "Category") or "").strip()
        raw_date = _te_get(row, "Date")
        if not raw_date:
            raise ValueError("Trading Economics row missing Date")
        scheduled = _te_datetime(str(raw_date))
        payload_hash = _hash_json(row)
        last_update = _te_get(row, "LastUpdate")
        output.append(
            PitSnapshot(
                provider="trading_economics",
                provider_event_id=provider_id,
                event_type=str(_te_get(row, "Category") or event_name),
                component=_slug(event_name),
                country=str(_te_get(row, "Country") or ""),
                currency=str(_te_get(row, "Currency") or ""),
                scheduled_at=scheduled,
                reference_period=str(_te_get(row, "Reference") or ""),
                unit=str(_te_get(row, "Unit") or "unspecified"),
                snapshot_at=capture_time,
                received_at=receive_time,
                actual=parse_number(str(_te_get(row, "Actual") or "")),
                consensus=parse_number(str(_te_get(row, "Forecast") or "")),
                previous=parse_number(str(_te_get(row, "Previous") or "")),
                revised=parse_number(str(_te_get(row, "Revised") or "")),
                source_url=str(_te_get(row, "SourceURL", "URL") or ""),
                license_class=license_class,
                rights_profile={name: bool(rights_profile.get(name, False)) for name in RIGHTS},
                payload_sha256=payload_hash,
                provenance=provenance,
                provider_updated_at=(
                    _te_datetime(str(last_update)) if last_update else None
                ),
            )
        )
    return output


def validate_component(snapshots: list[PitSnapshot]) -> dict[str, Any]:
    if not snapshots:
        raise ValueError("component requires at least one snapshot")
    first = snapshots[0]
    identity = (
        first.provider,
        first.provider_event_id,
        first.component,
        first.scheduled_at,
        first.reference_period,
    )
    issues: set[str] = set()
    parsed: list[tuple[datetime | None, PitSnapshot]] = []
    for snapshot in snapshots:
        current_identity = (
            snapshot.provider,
            snapshot.provider_event_id,
            snapshot.component,
            snapshot.scheduled_at,
            snapshot.reference_period,
        )
        if current_identity != identity:
            issues.add("unstable_event_identity")
        try:
            scheduled = _parse_aware(snapshot.scheduled_at)
            captured = _parse_aware(snapshot.snapshot_at)
            _parse_aware(snapshot.received_at)
        except ValueError:
            issues.add("naive_or_invalid_timestamp")
            scheduled = captured = None
        parsed.append((captured, snapshot))
    scheduled_at = _parse_aware(first.scheduled_at)
    pre = [
        item
        for captured, item in parsed
        if captured is not None
        and scheduled_at is not None
        and captured < scheduled_at
        and item.consensus is not None
    ]
    post = [
        item
        for captured, item in parsed
        if captured is not None
        and scheduled_at is not None
        and captured >= scheduled_at
        and item.actual is not None
    ]
    if not any(captured is not None and captured < scheduled_at for captured, _ in parsed if scheduled_at):
        issues.add("missing_pre_release_snapshot_at")
    if not pre:
        issues.add("unproven_consensus_vintage")
    if not post:
        issues.add("missing_post_release_actual_vintage")
    if any(not all(item.rights_profile.get(name, False) for name in RIGHTS) for _, item in parsed):
        issues.add("research_only_or_unknown_rights")
    if any(not item.unit or item.unit == "unspecified" for _, item in parsed):
        issues.add("missing_unit")
    if any(not item.source_url for _, item in parsed):
        issues.add("missing_source_url")
    if len({(item.snapshot_at, item.payload_sha256) for _, item in parsed}) != len(parsed):
        issues.add("duplicate_snapshot_payload")

    selected_pre = max(pre, key=lambda item: item.snapshot_at or "") if pre else None
    selected_post = min(post, key=lambda item: item.snapshot_at or "") if post else None
    revision_history = [
        {
            "snapshot_at": item.snapshot_at,
            "previous": item.previous,
            "revised": item.revised,
            "payload_sha256": item.payload_sha256,
        }
        for _, item in sorted(
            parsed, key=lambda pair: pair[0] or datetime.min.replace(tzinfo=UTC)
        )
        if item.revised is not None
    ]
    eligible = not issues
    return {
        "provider": first.provider,
        "provider_event_id": first.provider_event_id,
        "event_type": first.event_type,
        "component": first.component,
        "country": first.country,
        "currency": first.currency,
        "scheduled_at": first.scheduled_at,
        "reference_period": first.reference_period,
        "snapshot_count": len(snapshots),
        "eligible_for_price_join": eligible,
        "issues": sorted(issues),
        "consensus": selected_pre.consensus if selected_pre else None,
        "actual": selected_post.actual if selected_post else None,
        "previous_as_published": selected_pre.previous if selected_pre else None,
        "revised_previous_at_release": selected_post.revised if selected_post else None,
        "latest_revised_previous": (
            revision_history[-1]["revised"] if revision_history else None
        ),
        "revision_history": revision_history,
        "consensus_snapshot_at": selected_pre.snapshot_at if selected_pre else None,
        "actual_snapshot_at": selected_post.snapshot_at if selected_post else None,
        "surprise": (
            selected_post.actual - selected_pre.consensus
            if selected_pre and selected_post and selected_post.actual is not None and selected_pre.consensus is not None
            else None
        ),
    }


def audit_components(snapshots: Iterable[PitSnapshot]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[PitSnapshot]] = {}
    for snapshot in snapshots:
        grouped.setdefault(
            (snapshot.provider, snapshot.provider_event_id, snapshot.component), []
        ).append(snapshot)
    return [validate_component(grouped[key]) for key in sorted(grouped)]


def build_calendar_bundles(audits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for audit in audits:
        key = (audit["country"], audit["currency"], audit["scheduled_at"])
        grouped.setdefault(key, []).append(audit)
    bundles: list[dict[str, Any]] = []
    for key in sorted(grouped):
        components = sorted(grouped[key], key=lambda item: item["component"])
        identity = "\0".join(key).encode("utf-8")
        bundles.append(
            {
                "bundle_id": "calendar:" + hashlib.sha256(identity).hexdigest()[:20],
                "bundle_kind": "calendar_release",
                "country": key[0],
                "currency": key[1],
                "scheduled_at": key[2],
                "event_types": sorted({item["event_type"] for item in components}),
                "component_count": len(components),
                "components": components,
                "eligible_for_price_join": all(
                    item["eligible_for_price_join"] for item in components
                ),
                "issues": sorted({issue for item in components for issue in item["issues"]}),
            }
        )
    return bundles


def load_official_feature_bundles(
    documents_path: Path, fomc_features_path: Path, eia_features_path: Path
) -> list[dict[str, Any]]:
    documents = {
        row["document_id"]: row
        for row in json.loads(documents_path.read_text(encoding="utf-8"))
    }
    with fomc_features_path.open(newline="", encoding="utf-8") as handle:
        fomc = list(csv.DictReader(handle))
    with eia_features_path.open(newline="", encoding="utf-8") as handle:
        eia = list(csv.DictReader(handle))
    output: list[dict[str, Any]] = []
    for kind, rows in (("fomc_statement", fomc), ("eia_wpsr", eia)):
        for row in rows:
            document = documents[row["document_id"]]
            features = {
                name: float(value)
                for name, value in row.items()
                if value not in (None, "")
                and (
                    name.startswith("axis_")
                    or name.endswith("_inventory_change_mmbbl")
                )
            }
            issues = ["historical_live_arrival_unrecovered"]
            if "inferred" in document["timestamp_basis"]:
                issues.append("publication_time_schedule_inferred")
            output.append(
                {
                    "bundle_id": f"official:{document['source_event_id']}",
                    "bundle_kind": "official_feature",
                    "source": document["source"],
                    "source_event_id": document["source_event_id"],
                    "document_type": kind,
                    "scheduled_at": document["scheduled_at"],
                    "published_at": document["published_at"],
                    "feature_ready_at": document["feature_ready_at"],
                    "timestamp_basis": document["timestamp_basis"],
                    "features": features,
                    "eligible_for_price_join": False,
                    "issues": issues,
                }
            )
    return sorted(output, key=lambda item: (item["scheduled_at"], item["bundle_id"]))


def bundle_hash(bundles: Iterable[dict[str, Any]]) -> str:
    return _hash_json(list(bundles))


def write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            value = dict(row)
            for key, item in value.items():
                if isinstance(item, (list, dict)):
                    value[key] = json.dumps(item, ensure_ascii=False, sort_keys=True)
            writer.writerow(value)
