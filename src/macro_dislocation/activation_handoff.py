from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .campaign_roster import CampaignRoster, CampaignWindow
from .vendor_capture import VendorCaptureStore


UTC = timezone.utc
BINDING_FIELDS = (
    "binding_id",
    "source_event_id",
    "provider",
    "capture_id",
    "captured_at",
    "provenance",
    "license_class",
    "rights_profile",
    "components",
)
COMPONENT_FIELDS = (
    "logical_component",
    "provider_event_id",
    "provider_indicator",
    "scheduled_at",
    "reference_period",
    "unit",
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
    return value.astimezone(UTC).isoformat()


def shadow_schedule_bytes(schedule: dict[str, Any]) -> bytes:
    return (
        json.dumps(schedule, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def audit_component_binding(
    binding: dict[str, Any],
    window: CampaignWindow,
    evaluated_at: str,
    policy: dict[str, Any],
    *,
    capture_store: VendorCaptureStore | None = None,
) -> dict[str, Any]:
    structural: set[str] = set()
    eligibility: set[str] = set()
    if any(name not in binding for name in BINDING_FIELDS):
        structural.add("binding_schema_mismatch")

    if str(binding.get("source_event_id") or "") != window.source_event_id:
        structural.add("source_event_id_mismatch")
    if str(binding.get("provider") or "").lower() != str(policy["provider"]).lower():
        structural.add("provider_mismatch")
    capture_id = str(binding.get("capture_id") or "")
    if re.fullmatch(r"[0-9a-f]{64}", capture_id) is None:
        structural.add("invalid_capture_id")

    now = _parse_utc(evaluated_at)
    scheduled = _parse_utc(window.scheduled_at)
    captured: datetime | None = None
    try:
        captured = _parse_utc(str(binding.get("captured_at") or ""))
    except ValueError:
        structural.add("invalid_binding_timestamp")
    if captured is not None:
        if captured > now:
            structural.add("binding_capture_in_future")
        if captured >= scheduled:
            structural.add("binding_not_pre_release")
        if (scheduled - captured).total_seconds() > policy["binding_max_age_seconds"]:
            structural.add("binding_snapshot_stale")

    components = binding.get("components")
    if not isinstance(components, list):
        components = []
        structural.add("binding_schema_mismatch")
    normalized: list[dict[str, str]] = []
    logical_counts: dict[str, int] = {}
    provider_ids: list[str] = []
    for item in components:
        if not isinstance(item, dict) or any(
            name not in item for name in COMPONENT_FIELDS
        ):
            structural.add("component_schema_mismatch")
            continue
        normalized_item = {name: str(item.get(name) or "") for name in COMPONENT_FIELDS}
        logical = normalized_item["logical_component"]
        provider_id = normalized_item["provider_event_id"]
        logical_counts[logical] = logical_counts.get(logical, 0) + 1
        provider_ids.append(provider_id)
        if not provider_id or not normalized_item["provider_indicator"]:
            structural.add("invalid_provider_component")
        try:
            component_time = _iso(_parse_utc(normalized_item["scheduled_at"]))
        except ValueError:
            structural.add("invalid_provider_schedule")
        else:
            if component_time != window.scheduled_at:
                structural.add("provider_schedule_mismatch")
        if normalized_item["reference_period"] != window.reference_month:
            structural.add("reference_period_mismatch")
        if not normalized_item["unit"]:
            structural.add("missing_component_unit")
        normalized.append(normalized_item)

    expected = set(window.expected_logical_components)
    observed = set(logical_counts)
    if expected - observed:
        structural.add("missing_logical_component")
    if observed - expected:
        structural.add("unexpected_logical_component")
    if any(count != 1 for count in logical_counts.values()):
        structural.add("duplicate_logical_component")
    if len(provider_ids) != len(set(provider_ids)):
        structural.add("duplicate_provider_event_id")

    provenance = str(binding.get("provenance") or "")
    license_class = str(binding.get("license_class") or "")
    if "synthetic" in provenance.lower() or "synthetic" in license_class.lower():
        eligibility.add("synthetic_binding_not_empirical")
    elif provenance != "licensed_vendor_snapshot":
        eligibility.add("unlicensed_binding_provenance")
    raw_rights = binding.get("rights_profile")
    rights = raw_rights if isinstance(raw_rights, dict) else {}
    if not isinstance(raw_rights, dict) or any(
        rights.get(name) is not True for name in policy["required_rights"]
    ):
        eligibility.add("missing_binding_rights")

    capture_receipt_verified = False
    capture_integrity_hash: str | None = None
    if capture_store is None:
        eligibility.add("capture_receipt_not_verified")
    else:
        try:
            integrity = capture_store.integrity_report()
            observations = capture_store.observations()
            snapshots_by_capture = capture_store.replay_index()
        except (OSError, ValueError, json.JSONDecodeError):
            structural.add("capture_store_integrity_failed")
        else:
            capture_integrity_hash = _hash_json(integrity)
            if integrity.get("passed") is not True:
                structural.add("capture_store_integrity_failed")
            matches = [
                item for item in observations if item.get("capture_id") == capture_id
            ]
            if len(matches) != 1:
                structural.add("unknown_capture_id")
            else:
                observation = matches[0]
                if (
                    str(observation.get("provider") or "").lower()
                    != str(policy["provider"]).lower()
                    or observation.get("transport") != "https_snapshot"
                ):
                    structural.add("capture_transport_mismatch")
                if observation.get("provenance") != "authenticated_api_snapshot":
                    eligibility.add("capture_provenance_not_licensed")
                if observation.get("license_class") != license_class:
                    structural.add("capture_license_mismatch")
                observed_rights = observation.get("rights_profile")
                if not isinstance(observed_rights, dict) or any(
                    observed_rights.get(name) is not rights.get(name)
                    for name in policy["required_rights"]
                ):
                    structural.add("capture_rights_mismatch")
                try:
                    received_at = _iso(_parse_utc(str(observation["received_at"])))
                except (KeyError, ValueError):
                    structural.add("capture_timestamp_mismatch")
                else:
                    if captured is None or received_at != _iso(captured):
                        structural.add("capture_timestamp_mismatch")

                snapshots = snapshots_by_capture.get(capture_id, [])
                snapshots_by_id = {
                    item.provider_event_id: item for item in snapshots
                }
                if len(snapshots_by_id) != len(snapshots):
                    structural.add("duplicate_capture_provider_event_id")
                for item in normalized:
                    snapshot = snapshots_by_id.get(item["provider_event_id"])
                    if snapshot is None:
                        structural.add("provider_component_not_in_capture")
                        continue
                    if snapshot.scheduled_at != window.scheduled_at:
                        structural.add("capture_schedule_mismatch")
                    if snapshot.event_type != item["provider_indicator"]:
                        structural.add("capture_provider_indicator_mismatch")
                    if snapshot.reference_period != item["reference_period"]:
                        structural.add("capture_reference_period_mismatch")
                    if snapshot.unit != item["unit"]:
                        structural.add("capture_unit_mismatch")
                    if snapshot.actual is not None:
                        structural.add("capture_contains_pre_release_actual")
                    if snapshot.license_class != license_class:
                        structural.add("capture_license_mismatch")
                    if any(
                        snapshot.rights_profile.get(name) is not True
                        for name in policy["required_rights"]
                    ):
                        structural.add("capture_rights_mismatch")
                capture_receipt_verified = not any(
                    issue.startswith("capture_")
                    or issue in {
                        "unknown_capture_id",
                        "provider_component_not_in_capture",
                        "duplicate_capture_provider_event_id",
                    }
                    for issue in structural | eligibility
                )
            if not capture_receipt_verified:
                eligibility.add("capture_receipt_not_verified")

    result = {
        "binding_id": str(binding.get("binding_id") or ""),
        "source_event_id": window.source_event_id,
        "capture_id": capture_id,
        "evaluated_at": _iso(now),
        "expected_logical_components": sorted(expected),
        "observed_logical_components": sorted(observed),
        "provider_event_ids": sorted(provider_ids),
        "structurally_complete": not structural,
        "execution_eligible": not structural and not eligibility,
        "capture_receipt_verified": capture_receipt_verified,
        "capture_integrity_hash": capture_integrity_hash,
        "structural_issues": sorted(structural),
        "eligibility_issues": sorted(eligibility),
        "issues": sorted(structural | eligibility),
        "binding_payload_hash": _hash_json(binding),
    }
    result["binding_audit_hash"] = _hash_json(result)
    return result


def build_shadow_schedule_preview(
    roster: CampaignRoster,
    window: CampaignWindow,
    binding: dict[str, Any],
    binding_audit: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    by_logical = {
        str(item["logical_component"]): str(item["provider_event_id"])
        for item in binding.get("components", [])
        if isinstance(item, dict)
        and item.get("logical_component")
        and item.get("provider_event_id")
    }
    expected_ids = [
        by_logical.get(logical, f"UNRESOLVED:{logical}")
        for logical in window.expected_logical_components
    ]
    schedule = {
        "schedule_source": "phase7_activation_handoff",
        "schedule_source_url": window.schedule_source_url,
        "captured_at": str(binding.get("captured_at") or roster.checked_at),
        "bundles": [
            {
                "provider_bundle_id": (
                    f"{policy['provider']}:{window.source_event_id}:"
                    f"{binding_audit['binding_payload_hash'][:16]}"
                ),
                "event_family": window.event_family,
                "country": policy["country"],
                "currency": policy["currency"],
                "scheduled_at": window.scheduled_at,
                "expected_components": expected_ids,
            }
        ],
    }
    return schedule


def compile_activation_handoff(
    roster: CampaignRoster,
    window: CampaignWindow,
    binding: dict[str, Any],
    binding_audit: dict[str, Any],
    activation_packet: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    schedule = build_shadow_schedule_preview(
        roster, window, binding, binding_audit, policy
    )
    schedule_sha256 = _hash_bytes(shadow_schedule_bytes(schedule))
    issues = set(binding_audit["issues"])
    activation_ready = activation_packet.get("activation_status") == "READY_FOR_ACTIVATION"
    if not activation_ready:
        issues.add("activation_status_not_ready")
    executable = (
        activation_ready
        and binding_audit["execution_eligible"] is True
        and binding_audit.get("capture_receipt_verified") is True
    )
    if executable:
        status = "AUTHORIZED_FOR_SHADOW_CAPTURE"
    elif activation_packet.get("activation_status") == "BLOCKED_VENDOR_ACCESS":
        status = "BLOCKED_VENDOR_ACCESS"
    elif not activation_ready:
        status = "BLOCKED_ACTIVATION_GATE"
    else:
        status = "BLOCKED_COMPONENT_BINDING"

    core = {
        "roster_id": roster.roster_id,
        "roster_sha256": roster.roster_sha256,
        "source_event_id": window.source_event_id,
        "event_family": window.event_family,
        "scheduled_at": window.scheduled_at,
        "binding_id": binding_audit["binding_id"],
        "binding_payload_hash": binding_audit["binding_payload_hash"],
        "binding_audit_hash": binding_audit["binding_audit_hash"],
        "activation_packet_hash": activation_packet.get("packet_hash"),
        "shadow_schedule_sha256": schedule_sha256,
        "evaluated_at": activation_packet.get("evaluated_at"),
        "handoff_status": status,
        "executable": executable,
        "issues": sorted(issues),
    }
    handoff_id = "handoff:" + _hash_json(core)
    permit = None
    if executable:
        permit_core = {
            "permit_id": "permit:" + _hash_json({**core, "handoff_id": handoff_id}),
            "action": "shadow_capture",
            "handoff_id": handoff_id,
            "source_event_id": window.source_event_id,
            "issued_at": activation_packet.get("evaluated_at"),
            "expires_at": window.scheduled_at,
            "roster_sha256": roster.roster_sha256,
            "binding_payload_hash": binding_audit["binding_payload_hash"],
            "shadow_schedule_sha256": schedule_sha256,
        }
        permit_core["permit_hash"] = _hash_json(permit_core)
        permit = permit_core
    result = {
        **core,
        "handoff_id": handoff_id,
        "shadow_schedule_preview": schedule,
        "execution_permit": permit,
    }
    result["handoff_hash"] = _hash_json(result)
    return result
