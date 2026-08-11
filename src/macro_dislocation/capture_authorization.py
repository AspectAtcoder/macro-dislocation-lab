from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .campaign_roster import CampaignRoster, CampaignWindow


UTC = timezone.utc
AUTHORIZATION_KEY_ENV = "MACRO_LAB_AUTHORIZATION_KEY"
RECEIPT_FIELDS = (
    "receipt_id",
    "receipt_status",
    "roster_id",
    "roster_sha256",
    "source_event_id",
    "event_family",
    "scheduled_at",
    "authorized_at",
    "access_ready_by",
    "valid_until",
    "schedule_checked_at",
    "schedule_source_url",
    "activation_packet_hash",
    "rights_attestation_sha256",
    "license_class",
    "credential_present",
    "rights_attestation_valid",
    "provenance",
    "receipt_signature",
)
PERMIT_FIELDS = (
    "permit_id",
    "permit_status",
    "action",
    "source_event_id",
    "event_family",
    "scheduled_at",
    "issued_at",
    "not_before",
    "not_after",
    "roster_sha256",
    "access_receipt_id",
    "access_receipt_signature",
    "permit_signature",
)
DEFAULT_POLICY = {
    "authorization_key_environment_variable": AUTHORIZATION_KEY_ENV,
    "minimum_authorization_key_characters": 32,
    "pre_snapshot_max_age_seconds": 180,
    "stream_lead_seconds": 120,
    "stream_tail_seconds": 120,
    "allowed_actions": [
        "binding_snapshot",
        "pre_release_snapshot",
        "calendar_stream",
    ],
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be offset-aware: {value}")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _payload_hash(value: dict[str, Any], *excluded: str) -> str:
    return _sha256_bytes(
        _canonical({key: item for key, item in value.items() if key not in excluded})
    )


def _authorization_key(
    policy: dict[str, Any], *, key_override: bytes | None = None
) -> bytes:
    if key_override is not None:
        key = key_override
    else:
        name = str(
            policy.get("authorization_key_environment_variable")
            or AUTHORIZATION_KEY_ENV
        )
        key = os.environ.get(name, "").encode("utf-8")
    minimum = int(policy.get("minimum_authorization_key_characters") or 32)
    if len(key) < minimum or key.strip() != key:
        raise ValueError("authorization signing key is missing or invalid")
    return key


def authorization_key_preflight(policy: dict[str, Any]) -> dict[str, Any]:
    name = str(
        policy.get("authorization_key_environment_variable") or AUTHORIZATION_KEY_ENV
    )
    present = bool(os.environ.get(name))
    try:
        _authorization_key(policy)
    except ValueError:
        valid = False
    else:
        valid = True
    return {
        "environment_variable": name,
        "present": present,
        "valid": valid,
        "issues": [] if valid else ["missing_authorization_signing_key"],
    }


def _signature(
    value: dict[str, Any], domain: str, key: bytes
) -> str:
    return hmac.new(
        key,
        domain.encode("ascii") + b"\0" + _canonical(value),
        hashlib.sha256,
    ).hexdigest()


def activation_packet_hash(packet: dict[str, Any]) -> str:
    return _payload_hash(packet, "packet_hash")


def _seal_access_receipt(core: dict[str, Any], key: bytes) -> dict[str, Any]:
    receipt = dict(core)
    receipt["receipt_id"] = "access:" + _payload_hash(receipt)[:32]
    receipt["receipt_signature"] = _signature(
        receipt, "macro-dislocation-lab/access-receipt/v1", key
    )
    return receipt


def _seal_capture_permit(core: dict[str, Any], key: bytes) -> dict[str, Any]:
    permit = dict(core)
    permit["permit_id"] = "permit:" + _payload_hash(permit)[:32]
    permit["permit_signature"] = _signature(
        permit, "macro-dislocation-lab/capture-permit/v1", key
    )
    return permit


def validate_access_receipt(
    receipt: dict[str, Any],
    roster: CampaignRoster,
    window: CampaignWindow,
    evaluated_at: str,
    policy: dict[str, Any],
    *,
    _key_override: bytes | None = None,
) -> list[str]:
    issues: set[str] = set()
    if any(name not in receipt for name in RECEIPT_FIELDS):
        return ["access_receipt_schema_mismatch"]
    identity = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_id", "receipt_signature"}
    }
    expected_id = "access:" + _payload_hash(identity)[:32]
    if receipt.get("receipt_id") != expected_id:
        issues.add("access_receipt_id_mismatch")
    try:
        key = _authorization_key(policy, key_override=_key_override)
    except ValueError:
        issues.add("missing_authorization_signing_key")
    else:
        signed = {name: value for name, value in receipt.items() if name != "receipt_signature"}
        expected_signature = _signature(
            signed, "macro-dislocation-lab/access-receipt/v1", key
        )
        if not hmac.compare_digest(
            str(receipt.get("receipt_signature") or ""), expected_signature
        ):
            issues.add("access_receipt_signature_mismatch")
    if receipt.get("receipt_status") != "AUTHORIZED":
        issues.add("access_receipt_not_authorized")
    if receipt.get("provenance") != "authorized_vendor_access":
        issues.add("access_receipt_provenance_invalid")
    if (
        receipt.get("roster_id") != roster.roster_id
        or receipt.get("roster_sha256") != roster.roster_sha256
        or receipt.get("source_event_id") != window.source_event_id
        or receipt.get("scheduled_at") != window.scheduled_at
    ):
        issues.add("access_receipt_roster_mismatch")
    if (
        receipt.get("access_ready_by") != window.access_ready_by
        or receipt.get("schedule_checked_at") != roster.checked_at
        or receipt.get("schedule_source_url") != window.schedule_source_url
    ):
        issues.add("access_receipt_schedule_mismatch")
    if receipt.get("credential_present") is not True:
        issues.add("access_receipt_credential_missing")
    if receipt.get("rights_attestation_valid") is not True:
        issues.add("access_receipt_rights_invalid")
    try:
        now = _parse_utc(evaluated_at)
        authorized = _parse_utc(str(receipt["authorized_at"]))
        deadline = _parse_utc(str(receipt["access_ready_by"]))
        valid_until = _parse_utc(str(receipt["valid_until"]))
    except (KeyError, ValueError):
        issues.add("access_receipt_timestamp_invalid")
    else:
        if authorized > deadline:
            issues.add("access_deadline_missed")
        if now > valid_until:
            issues.add("access_receipt_expired")
        if authorized > now:
            issues.add("access_receipt_not_yet_valid")
    return sorted(issues)


def issue_access_authorization(
    roster: CampaignRoster,
    window: CampaignWindow,
    activation_packet: dict[str, Any],
    rights_attestation_path: Path | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    # Local import avoids a module cycle: evidence_enrollment also consumes the
    # vendor capture layer that enforces these permits.
    from .evidence_enrollment import vendor_access_preflight

    preflight = vendor_access_preflight(rights_attestation_path)
    key_preflight = authorization_key_preflight(policy)
    issues: set[str] = set(preflight["issues"]) | set(key_preflight["issues"])
    packet_status = str(activation_packet.get("activation_status") or "")
    if packet_status == "BLOCKED_ACCESS_DEADLINE_MISSED":
        issues.add("access_deadline_missed")
    elif packet_status != "READY_FOR_ACTIVATION":
        issues.add("activation_status_not_ready")
    if activation_packet.get("packet_hash") != activation_packet_hash(activation_packet):
        issues.add("activation_packet_hash_mismatch")
    if (
        activation_packet.get("roster_id") != roster.roster_id
        or activation_packet.get("roster_sha256") != roster.roster_sha256
        or activation_packet.get("source_event_id") != window.source_event_id
    ):
        issues.add("activation_packet_roster_mismatch")
    try:
        authorized = _parse_utc(str(activation_packet.get("evaluated_at") or ""))
        deadline = _parse_utc(window.access_ready_by)
    except ValueError:
        issues.add("activation_packet_timestamp_invalid")
        authorized = _parse_utc(window.access_ready_by)
        deadline = authorized
    if authorized > deadline:
        issues.add("access_deadline_missed")

    receipt: dict[str, Any] | None = None
    if not issues:
        if rights_attestation_path is None:
            raise RuntimeError("ready preflight requires a rights attestation path")
        key = _authorization_key(policy)
        valid_until = _parse_utc(window.scheduled_at) + timedelta(
            seconds=int(policy["stream_tail_seconds"])
        )
        core = {
            "receipt_status": "AUTHORIZED",
            "roster_id": roster.roster_id,
            "roster_sha256": roster.roster_sha256,
            "source_event_id": window.source_event_id,
            "event_family": window.event_family,
            "scheduled_at": window.scheduled_at,
            "authorized_at": _iso(authorized),
            "access_ready_by": window.access_ready_by,
            "valid_until": _iso(valid_until),
            "schedule_checked_at": roster.checked_at,
            "schedule_source_url": window.schedule_source_url,
            "activation_packet_hash": activation_packet["packet_hash"],
            "rights_attestation_sha256": _sha256_path(rights_attestation_path),
            "license_class": preflight["license_class"],
            "credential_present": True,
            "rights_attestation_valid": True,
            "provenance": "authorized_vendor_access",
        }
        receipt = _seal_access_receipt(core, key)
    if "access_deadline_missed" in issues:
        status = "MISSED_ACCESS_DEADLINE"
    elif issues:
        status = "BLOCKED_EXTERNAL_ACCESS"
    else:
        status = "ACCESS_RECEIPT_ISSUED"
    return {
        "authorization_status": status,
        "evaluated_at": activation_packet.get("evaluated_at"),
        "source_event_id": window.source_event_id,
        "scheduled_at": window.scheduled_at,
        "access_ready_by": window.access_ready_by,
        "issues": sorted(issues),
        "credential_present": preflight["credential_present"],
        "rights_attestation_present": preflight["rights_attestation_present"],
        "rights_attestation_valid": preflight["rights_attestation_valid"],
        "authorization_signing_key_present": key_preflight["present"],
        "authorization_signing_key_valid": key_preflight["valid"],
        "access_receipt": receipt,
    }


def issue_capture_permit(
    receipt: dict[str, Any],
    roster: CampaignRoster,
    window: CampaignWindow,
    action: str,
    evaluated_at: str,
    policy: dict[str, Any],
    *,
    _key_override: bytes | None = None,
) -> dict[str, Any]:
    issues = set(
        validate_access_receipt(
            receipt,
            roster,
            window,
            evaluated_at,
            policy,
            _key_override=_key_override,
        )
    )
    if action not in policy["allowed_actions"]:
        issues.add("capture_permit_action_invalid")
    now = _parse_utc(evaluated_at)
    scheduled = _parse_utc(window.scheduled_at)
    if action == "binding_snapshot":
        not_before = _parse_utc(str(receipt.get("authorized_at") or evaluated_at))
        not_after = scheduled
    elif action == "pre_release_snapshot":
        not_before = scheduled - timedelta(
            seconds=int(policy["pre_snapshot_max_age_seconds"])
        )
        not_after = scheduled
    else:
        not_before = scheduled - timedelta(seconds=int(policy["stream_lead_seconds"]))
        not_after = scheduled + timedelta(seconds=int(policy["stream_tail_seconds"]))
    if now < not_before:
        issues.add("capture_action_too_early")
    if now >= scheduled:
        issues.add("capture_permit_issuance_expired")

    permit: dict[str, Any] | None = None
    if not issues:
        key = _authorization_key(policy, key_override=_key_override)
        core = {
            "permit_status": "AUTHORIZED",
            "action": action,
            "source_event_id": window.source_event_id,
            "event_family": window.event_family,
            "scheduled_at": window.scheduled_at,
            "issued_at": _iso(now),
            "not_before": _iso(not_before),
            "not_after": _iso(not_after),
            "roster_sha256": roster.roster_sha256,
            "access_receipt_id": receipt["receipt_id"],
            "access_receipt_signature": receipt["receipt_signature"],
        }
        permit = _seal_capture_permit(core, key)
    return {
        "permit_status": "CAPTURE_PERMIT_ISSUED" if permit else "CAPTURE_PERMIT_DENIED",
        "action": action,
        "evaluated_at": _iso(now),
        "issues": sorted(issues),
        "capture_permit": permit,
    }


def validate_capture_permit(
    permit: dict[str, Any],
    expected_action: str,
    evaluated_at: str,
    policy: dict[str, Any] | None = None,
    *,
    _key_override: bytes | None = None,
) -> list[str]:
    active_policy = policy or DEFAULT_POLICY
    issues: set[str] = set()
    if any(name not in permit for name in PERMIT_FIELDS):
        return ["capture_permit_schema_mismatch"]
    identity = {
        key: value
        for key, value in permit.items()
        if key not in {"permit_id", "permit_signature"}
    }
    expected_id = "permit:" + _payload_hash(identity)[:32]
    if permit.get("permit_id") != expected_id:
        issues.add("capture_permit_id_mismatch")
    try:
        key = _authorization_key(active_policy, key_override=_key_override)
    except ValueError:
        issues.add("missing_authorization_signing_key")
    else:
        signed = {name: value for name, value in permit.items() if name != "permit_signature"}
        expected_signature = _signature(
            signed, "macro-dislocation-lab/capture-permit/v1", key
        )
        if not hmac.compare_digest(
            str(permit.get("permit_signature") or ""), expected_signature
        ):
            issues.add("capture_permit_signature_mismatch")
    if permit.get("permit_status") != "AUTHORIZED":
        issues.add("capture_permit_not_authorized")
    if permit.get("action") != expected_action:
        issues.add("capture_permit_action_mismatch")
    if expected_action not in active_policy["allowed_actions"]:
        issues.add("capture_permit_action_invalid")
    try:
        now = _parse_utc(evaluated_at)
        not_before = _parse_utc(str(permit["not_before"]))
        not_after = _parse_utc(str(permit["not_after"]))
    except (KeyError, ValueError):
        issues.add("capture_permit_timestamp_invalid")
    else:
        if now < not_before:
            issues.add("capture_permit_not_yet_valid")
        if now > not_after:
            issues.add("capture_permit_expired")
    return sorted(issues)


def load_valid_capture_permit(
    path: Path,
    expected_action: str,
    evaluated_at: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError("capture authorization permit is required")
    try:
        permit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("capture authorization permit is invalid") from exc
    if not isinstance(permit, dict):
        raise RuntimeError("capture authorization permit is invalid")
    issues = validate_capture_permit(
        permit, expected_action, evaluated_at, policy or DEFAULT_POLICY
    )
    if issues:
        raise RuntimeError(f"capture authorization denied: {issues[0]}")
    return permit


def permit_covers_date_range(permit: dict[str, Any], start: str, end: str) -> bool:
    scheduled = _parse_utc(str(permit["scheduled_at"])).date()
    try:
        return date.fromisoformat(start) <= scheduled <= date.fromisoformat(end)
    except ValueError:
        return False


def next_viable_window(
    roster: CampaignRoster, evaluated_at: str
) -> CampaignWindow | None:
    now = _parse_utc(evaluated_at)
    return next(
        (
            window
            for window in roster.windows
            if _parse_utc(window.scheduled_at) > now
            and _parse_utc(window.access_ready_by) >= now
        ),
        None,
    )


def write_signed_artifact_once(path: Path, value: dict[str, Any]) -> None:
    """Write one signed receipt or permit without allowing in-place replacement."""
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError(f"authorization artifact already exists: {path}") from None
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
