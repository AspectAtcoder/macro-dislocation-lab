from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .pit_events import RIGHTS
from .shadow_campaign import (
    ReleaseWindowPlan,
    audit_shadow_trace,
    campaign_promotion_gate,
    normalize_trace_event,
    shadow_audit_hash,
)
from .vendor_capture import (
    VendorCaptureStore,
    load_rights_attestation,
)


UTC = timezone.utc
EVIDENCE_PACKAGE_FIELDS = (
    "package_id",
    "run_id",
    "plan_id",
    "event_family",
    "scheduled_at",
    "schedule_sha256",
    "window_audit_hash",
    "capture_integrity_hash",
    "referenced_capture_ids",
    "capture_reference_count",
    "structurally_complete",
    "enrollable",
    "issues",
    "package_hash",
)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be offset-aware: {value}")
    return parsed.astimezone(UTC)


def _replace_fixture_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_fixture_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_fixture_value(item, replacements)
            for key, item in value.items()
        }
    return value


def load_linked_trace_fixture(
    path: Path,
    plan: ReleaseWindowPlan,
    *,
    pre_capture_id: str,
    post_capture_id: str,
) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("linked trace fixture must be a list")
    replacements = {
        "$PLAN_ID": plan.plan_id,
        "$SCHEDULE_SHA256": plan.schedule_sha256,
        "$PRE_CAPTURE_ID": pre_capture_id,
        "$POST_CAPTURE_ID": post_capture_id,
    }
    return [
        normalize_trace_event(_replace_fixture_value(row, replacements))
        for row in rows
    ]


def evidence_package_hash(package: dict[str, Any]) -> str:
    return _hash_json(
        {key: value for key, value in package.items() if key != "package_hash"}
    )


def _evidence_package_id(package: dict[str, Any]) -> str:
    identity = {
        "run_id": package.get("run_id"),
        "plan_id": package.get("plan_id"),
        "window_audit_hash": package.get("window_audit_hash"),
        "capture_integrity_hash": package.get("capture_integrity_hash"),
        "referenced_capture_ids": package.get("referenced_capture_ids"),
    }
    return "evidence:" + _hash_json(identity)


def seal_evidence_package(package: dict[str, Any]) -> dict[str, Any]:
    """Refresh deterministic identities after constructing an evidence package."""
    package["package_id"] = _evidence_package_id(package)
    package["package_hash"] = evidence_package_hash(package)
    return package


def validate_evidence_package(package: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    missing = [field for field in EVIDENCE_PACKAGE_FIELDS if field not in package]
    if missing:
        return ["evidence_package_schema_mismatch"]
    if package.get("package_hash") != evidence_package_hash(package):
        issues.append("evidence_package_hash_mismatch")
    if package.get("package_id") != _evidence_package_id(package):
        issues.append("evidence_package_id_mismatch")
    window = package.get("window_audit")
    if not isinstance(window, dict):
        issues.append("missing_window_audit")
    elif (
        window.get("audit_hash") != shadow_audit_hash(window)
        or window.get("audit_hash") != package.get("window_audit_hash")
    ):
        issues.append("window_audit_hash_mismatch")
    if package.get("enrollable") is True and (
        package.get("issues") != []
        or package.get("structural_issues") != []
        or package.get("eligibility_issues") != []
        or not isinstance(window, dict)
        or window.get("operationally_complete") is not True
        or window.get("empirical_window") is not True
        or window.get("provenance") != "licensed_shadow"
        or window.get("issues") != []
    ):
        issues.append("invalid_enrollable_claim")
    return issues


def vendor_access_preflight(
    rights_attestation_path: Path | None = None,
) -> dict[str, Any]:
    credential_present = bool(os.environ.get("TRADING_ECONOMICS_API_KEY"))
    rights_present = bool(
        rights_attestation_path is not None and rights_attestation_path.is_file()
    )
    rights_valid = False
    license_class: str | None = None
    issues: list[str] = []
    if not credential_present:
        issues.append("missing_vendor_credential")
    if not rights_present:
        issues.append("missing_rights_attestation")
    else:
        try:
            license_class, rights = load_rights_attestation(rights_attestation_path)
            rights_valid = all(rights.values())
        except (OSError, ValueError, json.JSONDecodeError):
            issues.append("invalid_rights_attestation")
    return {
        "ready": credential_present and rights_present and rights_valid,
        "credential_environment_variable": "TRADING_ECONOMICS_API_KEY",
        "credential_present": credential_present,
        "rights_attestation_present": rights_present,
        "rights_attestation_valid": rights_valid,
        "license_class": license_class,
        "issues": sorted(set(issues)),
    }


def _store_claim(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    claims = [event["details"] for event in events if event["kind"] == "store_audit"]
    return claims[-1] if claims else None


def _is_synthetic_observation(observation: dict[str, Any]) -> bool:
    fields = "|".join(
        str(observation.get(name) or "").lower()
        for name in ("license_class", "provenance", "public_endpoint")
    )
    return any(word in fields for word in ("synthetic", "example.invalid", "test"))


def _official_schedule_source(plan: ReleaseWindowPlan) -> bool:
    host = (urlsplit(plan.schedule_source_url).hostname or "").lower()
    return host == "bls.gov" or host.endswith(".bls.gov")


def audit_evidence_records(
    plan: ReleaseWindowPlan,
    events: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    snapshots_by_capture: dict[str, list[dict[str, Any]]],
    integrity: dict[str, Any],
    policy: dict[str, Any],
    *,
    attested_license_class: str | None = None,
    attested_rights: dict[str, bool] | None = None,
) -> dict[str, Any]:
    window = audit_shadow_trace(plan, events, policy)
    structural_issues: set[str] = set()
    eligibility_issues: set[str] = set()
    observation_index: dict[str, dict[str, Any]] = {}
    for observation in observations:
        capture_id = str(observation.get("capture_id") or "")
        if capture_id in observation_index:
            structural_issues.add("duplicate_capture_id")
        observation_index[capture_id] = observation

    if integrity.get("passed") is not True:
        structural_issues.add("raw_store_integrity_failed")
    claim = _store_claim(events)
    claim_fields = (
        "passed",
        "violations",
        "observations",
        "unique_raw_blobs",
        "credential_persistence_matches",
    )
    if claim is None or any(claim.get(name) != integrity.get(name) for name in claim_fields):
        structural_issues.add("store_integrity_claim_mismatch")

    scheduled = _parse_utc(plan.scheduled_at)
    references: list[tuple[str, dict[str, Any], str]] = []
    for event in events:
        if event["kind"] == "pre_snapshot_captured":
            references.append(("pre", event, str(event["details"].get("capture_id") or "")))
        elif event["kind"] == "release_component":
            references.append(
                ("release", event, str(event["details"].get("capture_id") or ""))
            )
    referenced_capture_ids: list[str] = []
    for role, event, capture_id in references:
        if not capture_id:
            structural_issues.add("missing_capture_reference")
            continue
        referenced_capture_ids.append(capture_id)
        observation = observation_index.get(capture_id)
        if observation is None:
            structural_issues.add("unknown_capture_id")
            continue
        received = _parse_utc(str(observation["received_at"]))
        traced = _parse_utc(str(event["observed_at"]))
        delta_ms = abs((traced - received).total_seconds()) * 1000
        if not math.isfinite(delta_ms) or delta_ms > policy["maximum_capture_trace_delta_ms"]:
            structural_issues.add("capture_trace_clock_mismatch")
        snapshots = snapshots_by_capture.get(capture_id)
        if snapshots is None:
            structural_issues.add("capture_replay_missing")
            continue
        provider_ids = {
            str(snapshot.get("provider_event_id") or "") for snapshot in snapshots
        }
        if any(
            _parse_utc(str(snapshot["scheduled_at"])) != scheduled
            for snapshot in snapshots
        ):
            structural_issues.add("capture_schedule_mismatch")
        if role == "pre":
            if observation.get("transport") != "https_snapshot" or received >= scheduled:
                structural_issues.add("pre_capture_not_pre_release")
            expected = set(plan.expected_components)
            if not expected.issubset(provider_ids) or any(
                snapshot.get("actual") is not None
                or snapshot.get("consensus") is None
                for snapshot in snapshots
                if snapshot.get("provider_event_id") in expected
            ):
                structural_issues.add("pre_consensus_not_in_capture")
        else:
            component = str(event["details"].get("component_id") or "")
            matches = [
                snapshot
                for snapshot in snapshots
                if snapshot.get("provider_event_id") == component
                and snapshot.get("actual") is not None
            ]
            if observation.get("transport") != "websocket_calendar" or received < scheduled:
                structural_issues.add("release_capture_not_post_release")
            if not matches:
                structural_issues.add("component_not_in_capture")

    linked_observations = [
        observation_index[capture_id]
        for capture_id in sorted(set(referenced_capture_ids))
        if capture_id in observation_index
    ]
    if not _official_schedule_source(plan):
        eligibility_issues.add("synthetic_schedule_not_empirical")
    if window.get("provenance") != "licensed_shadow":
        eligibility_issues.add("nonlicensed_trace_provenance")
    if any(_is_synthetic_observation(item) for item in linked_observations):
        eligibility_issues.add("synthetic_capture_not_empirical")
    if any(
        not all(item.get("rights_profile", {}).get(name) is True for name in RIGHTS)
        for item in linked_observations
    ):
        eligibility_issues.add("capture_rights_incomplete")
    if attested_license_class is None or attested_rights is None:
        eligibility_issues.add("missing_rights_attestation")
    else:
        if not all(attested_rights.get(name) is True for name in RIGHTS):
            eligibility_issues.add("invalid_rights_attestation")
        if any(
            item.get("license_class") != attested_license_class
            or item.get("rights_profile") != attested_rights
            for item in linked_observations
        ):
            eligibility_issues.add("capture_rights_attestation_mismatch")
    allowed_provenance = {
        "authenticated_api_snapshot",
        "authenticated_calendar_stream",
    }
    if any(
        item.get("provenance") not in allowed_provenance
        for item in linked_observations
    ):
        eligibility_issues.add("synthetic_capture_not_empirical")

    structurally_complete = window["operationally_complete"] and not structural_issues
    enrollable = structurally_complete and not eligibility_issues
    all_issues = sorted(structural_issues | eligibility_issues)
    integrity_hash = _hash_json(integrity)
    package = {
        "package_id": "",
        "run_id": window["run_id"],
        "plan_id": plan.plan_id,
        "event_family": plan.event_family,
        "scheduled_at": plan.scheduled_at,
        "schedule_sha256": plan.schedule_sha256,
        "window_audit_hash": window["audit_hash"],
        "capture_integrity_hash": integrity_hash,
        "referenced_capture_ids": sorted(set(referenced_capture_ids)),
        "capture_reference_count": len(referenced_capture_ids),
        "structurally_complete": structurally_complete,
        "enrollable": enrollable,
        "structural_issues": sorted(structural_issues),
        "eligibility_issues": sorted(eligibility_issues),
        "issues": all_issues,
        "window_audit": window,
        "capture_integrity": integrity,
    }
    return seal_evidence_package(package)


def audit_evidence_package(
    plan: ReleaseWindowPlan,
    events: list[dict[str, Any]],
    store: VendorCaptureStore,
    policy: dict[str, Any],
    *,
    rights_attestation_path: Path | None = None,
    forbidden_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    integrity = store.integrity_report(forbidden_values=forbidden_values)
    observations = store.observations()
    snapshots_by_capture = {
        capture_id: [asdict(snapshot) for snapshot in snapshots]
        for capture_id, snapshots in store.replay_index().items()
    }
    license_class: str | None = None
    rights: dict[str, bool] | None = None
    if rights_attestation_path is not None:
        license_class, rights = load_rights_attestation(rights_attestation_path)
    return audit_evidence_records(
        plan,
        events,
        observations,
        snapshots_by_capture,
        integrity,
        policy,
        attested_license_class=license_class,
        attested_rights=rights,
    )


def validate_ledger_candidates(packages: list[dict[str, Any]]) -> dict[str, Any]:
    issues: set[str] = set()
    seen_packages: set[str] = set()
    seen_runs: set[str] = set()
    seen_plans: set[str] = set()
    seen_releases: set[tuple[str, str]] = set()
    for package in packages:
        package_id = str(package.get("package_id") or "")
        run_id = str(package.get("run_id") or "")
        plan_id = str(package.get("plan_id") or "")
        release = (
            str(package.get("event_family") or "").upper(),
            str(package.get("scheduled_at") or ""),
        )
        if package_id in seen_packages:
            issues.add("duplicate_evidence_package")
        if run_id in seen_runs:
            issues.add("duplicate_run_id")
        if plan_id in seen_plans:
            issues.add("duplicate_plan_id")
        if release in seen_releases:
            issues.add("duplicate_release_window")
        seen_packages.add(package_id)
        seen_runs.add(run_id)
        seen_plans.add(plan_id)
        seen_releases.add(release)
        issues.update(validate_evidence_package(package))
    return {"passed": not issues, "issues": sorted(issues), "records": len(packages)}


class EvidenceLedger:
    """Append-only ledger containing only fully enrollable evidence packages."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "evidence.jsonl"
        self.lock_path = root / "evidence.lock"
        root.mkdir(parents=True, exist_ok=True)

    def packages(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        output: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise ValueError(f"torn evidence ledger line: {line_number}")
                try:
                    package = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid evidence ledger JSON: {line_number}") from exc
                issues = validate_evidence_package(package)
                if issues:
                    raise ValueError(f"invalid evidence package at line {line_number}: {issues[0]}")
                output.append(package)
        ledger = validate_ledger_candidates(output)
        if not ledger["passed"]:
            raise ValueError(ledger["issues"][0])
        return output

    def append(self, package: dict[str, Any]) -> dict[str, Any]:
        issues = validate_evidence_package(package)
        if issues:
            raise ValueError(issues[0])
        if package.get("enrollable") is not True or package.get("issues") != []:
            raise ValueError("evidence_package_not_enrollable")
        line = (
            json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        lock_descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            existing = self.packages()
            candidate = [*existing, package]
            ledger = validate_ledger_candidates(candidate)
            if not ledger["passed"]:
                raise ValueError(ledger["issues"][0])
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            try:
                written = 0
                while written < len(line):
                    written += os.write(descriptor, line[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        return package


def campaign_checkpoint(
    packages: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    ledger = validate_ledger_candidates(packages)
    eligible = [
        package
        for package in packages
        if package.get("enrollable") is True
        and package.get("issues") == []
        and not validate_evidence_package(package)
    ]
    campaign = campaign_promotion_gate(
        [package["window_audit"] for package in eligible], policy
    )
    reasons = [*ledger["issues"], *campaign["reasons"]]
    result = {
        "promoted": ledger["passed"] and campaign["promoted"],
        "ledger_records": len(packages),
        "eligible_packages": len(eligible),
        "complete_empirical_windows": campaign["complete_empirical_windows"],
        "complete_cpi_windows": campaign["complete_cpi_windows"],
        "complete_nfp_windows": campaign["complete_nfp_windows"],
        "reasons": reasons,
        "ledger_audit": ledger,
        "window_campaign": campaign,
    }
    result["checkpoint_hash"] = _hash_json(result)
    return result
