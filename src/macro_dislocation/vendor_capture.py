from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .pit_events import RIGHTS, PitSnapshot, normalize_trading_economics_snapshot


UTC = timezone.utc
TE_API_ROOT = "https://api.tradingeconomics.com"
CAPTURE_OBSERVATION_FIELDS = (
    "capture_id",
    "provider",
    "transport",
    "public_endpoint",
    "request_started_at",
    "received_at",
    "received_monotonic_ns",
    "http_status",
    "payload_sha256",
    "payload_bytes",
    "license_class",
    "rights_profile",
    "provenance",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def capture_observation_id(observation: dict[str, Any]) -> str:
    """Recompute the content identity of one capture receipt envelope."""
    core = {
        name: observation[name]
        for name in CAPTURE_OBSERVATION_FIELDS
        if name != "capture_id"
    }
    return sha256_bytes(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _aware_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be offset-aware: {value}")
    return parsed.astimezone(UTC).isoformat()


def public_endpoint(url: str) -> str:
    """Return a persistable endpoint with credentials and fragments removed."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "wss"} or not parsed.hostname:
        raise ValueError("vendor endpoint must be an https or wss URL")
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _json_rows(payload: bytes) -> list[dict[str, Any]]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("vendor payload is not valid UTF-8 JSON") from exc
    rows = value if isinstance(value, list) else [value]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("vendor payload must be one object or a non-empty object list")
    for row in rows:
        topic = row.get("topic") or row.get("Topic")
        if topic not in (None, "", "calendar"):
            raise ValueError(f"unexpected stream topic: {topic}")
    return rows


def validate_rights_attestation(value: dict[str, Any]) -> tuple[str, dict[str, bool]]:
    """Validate written production rights before any network or stream capture."""
    if value.get("approved") is not True:
        raise ValueError("rights attestation is not approved")
    agreement_id = str(value.get("agreement_id") or "").strip()
    approved_by = str(value.get("approved_by") or "").strip()
    license_class = str(value.get("license_class") or "").strip()
    provider = str(value.get("provider") or "").strip().lower()
    forbidden = ("example", "placeholder", "synthetic", "test")
    if not agreement_id or any(word in agreement_id.lower() for word in forbidden):
        raise ValueError("rights attestation requires a non-placeholder agreement_id")
    if not approved_by:
        raise ValueError("rights attestation requires approved_by")
    if provider != "trading economics":
        raise ValueError("rights attestation provider must be Trading Economics")
    if not license_class or any(word in license_class.lower() for word in forbidden):
        raise ValueError("rights attestation requires a production license_class")
    _aware_utc(str(value.get("attested_at") or ""))
    raw_rights = value.get("rights")
    if not isinstance(raw_rights, dict):
        raise ValueError("rights attestation requires a rights object")
    rights = {name: raw_rights.get(name) is True for name in RIGHTS}
    missing = [name for name, allowed in rights.items() if not allowed]
    if missing:
        raise ValueError(f"rights attestation missing required rights: {', '.join(missing)}")
    return license_class, rights


def load_rights_attestation(path: Path) -> tuple[str, dict[str, bool]]:
    return validate_rights_attestation(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class CaptureResult:
    observation: dict[str, Any]
    snapshots: list[PitSnapshot]
    inserted_blob: bool


class VendorCaptureStore:
    """Content-addressed payloads plus an append-only receipt log."""

    def __init__(self, root: Path):
        self.root = root
        self.raw_root = root / "raw"
        self.observations_path = root / "observations.jsonl"
        self.raw_root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        return self.raw_root / digest[:2] / f"{digest}.json"

    def _write_blob_once(self, payload: bytes, digest: str) -> bool:
        path = self._blob_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            existing = path.read_bytes()
            if existing != payload or sha256_bytes(existing) != digest:
                raise ValueError(f"content-address collision or corrupt blob: {digest}")
            return False
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return True

    def _append_observation(self, observation: dict[str, Any]) -> None:
        line = (
            json.dumps(observation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(
            self.observations_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            written = 0
            while written < len(line):
                written += os.write(descriptor, line[written:])
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def capture(
        self,
        payload: bytes,
        *,
        provider: str,
        transport: str,
        endpoint: str,
        request_started_at: str,
        received_at: str,
        received_monotonic_ns: int,
        http_status: int | None,
        license_class: str,
        rights_profile: dict[str, bool],
        provenance: str,
    ) -> CaptureResult:
        rows = _json_rows(payload)
        started = _aware_utc(request_started_at)
        received = _aware_utc(received_at)
        if datetime.fromisoformat(started) > datetime.fromisoformat(received):
            raise ValueError("request_started_at must not be after received_at")
        if not isinstance(received_monotonic_ns, int) or received_monotonic_ns < 0:
            raise ValueError("received_monotonic_ns must be a non-negative integer")
        if transport not in {"https_snapshot", "websocket_calendar", "synthetic_fixture"}:
            raise ValueError(f"unsupported transport: {transport}")
        normalized = normalize_trading_economics_snapshot(
            rows,
            snapshot_at=received,
            received_at=received,
            rights_profile=rights_profile,
            license_class=license_class,
            provenance=provenance,
        )
        digest = sha256_bytes(payload)
        safe_endpoint = public_endpoint(endpoint)
        core = {
            "provider": provider,
            "transport": transport,
            "public_endpoint": safe_endpoint,
            "request_started_at": started,
            "received_at": received,
            "received_monotonic_ns": received_monotonic_ns,
            "http_status": http_status,
            "payload_sha256": digest,
            "payload_bytes": len(payload),
            "license_class": license_class,
            "rights_profile": {
                name: rights_profile.get(name) is True for name in RIGHTS
            },
            "provenance": provenance,
        }
        observation = {"capture_id": "", **core}
        observation["capture_id"] = capture_observation_id(observation)
        inserted = self._write_blob_once(payload, digest)
        self._append_observation(observation)
        return CaptureResult(observation, normalized, inserted)

    def observations(self) -> list[dict[str, Any]]:
        if not self.observations_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        with self.observations_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise ValueError(f"torn observation line: {line_number}")
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid observation JSON: {line_number}") from exc
                missing = [name for name in CAPTURE_OBSERVATION_FIELDS if name not in row]
                if missing:
                    raise ValueError(
                        f"observation {line_number} missing fields: {', '.join(missing)}"
                    )
                rows.append(row)
        return rows

    def _replay_observation(self, observation: dict[str, Any]) -> list[PitSnapshot]:
        digest = observation["payload_sha256"]
        path = self._blob_path(digest)
        if not path.is_file():
            raise ValueError(f"missing raw payload: {digest}")
        payload = path.read_bytes()
        if sha256_bytes(payload) != digest:
            raise ValueError(f"raw payload hash mismatch: {digest}")
        if len(payload) != observation["payload_bytes"]:
            raise ValueError(f"raw payload size mismatch: {digest}")
        rows = _json_rows(payload)
        return normalize_trading_economics_snapshot(
            rows,
            snapshot_at=observation["received_at"],
            received_at=observation["received_at"],
            rights_profile=observation["rights_profile"],
            license_class=observation["license_class"],
            provenance=observation["provenance"],
        )

    def replay_index(self) -> dict[str, list[PitSnapshot]]:
        """Replay immutable blobs while retaining their receipt identities."""
        output: dict[str, list[PitSnapshot]] = {}
        for observation in self.observations():
            capture_id = str(observation["capture_id"])
            if capture_id in output:
                raise ValueError(f"duplicate capture_id: {capture_id}")
            output[capture_id] = self._replay_observation(observation)
        return output

    def replay(self) -> list[PitSnapshot]:
        return [
            snapshot
            for snapshots in self.replay_index().values()
            for snapshot in snapshots
        ]

    def integrity_report(self, *, forbidden_values: Iterable[str] = ()) -> dict[str, Any]:
        violations: list[str] = []
        try:
            observations = self.observations()
        except ValueError as exc:
            return {
                "passed": False,
                "violations": [str(exc)],
                "observations": 0,
                "unique_raw_blobs": 0,
                "credential_persistence_matches": 0,
            }
        digests: set[str] = set()
        capture_ids: set[str] = set()
        for row in observations:
            capture_id = str(row["capture_id"])
            if capture_id in capture_ids:
                violations.append(f"duplicate capture_id: {capture_id}")
            capture_ids.add(capture_id)
            if capture_observation_id(row) != capture_id:
                violations.append(f"capture observation hash mismatch: {capture_id}")
            digest = str(row["payload_sha256"])
            digests.add(digest)
            path = self._blob_path(digest)
            if not path.is_file():
                violations.append(f"missing raw payload: {digest}")
                continue
            payload = path.read_bytes()
            if sha256_bytes(payload) != digest:
                violations.append(f"raw payload hash mismatch: {digest}")
            if len(payload) != row["payload_bytes"]:
                violations.append(f"raw payload size mismatch: {digest}")
        matches = 0
        forbidden = [value.encode("utf-8") for value in forbidden_values if value]
        if forbidden:
            paths = list(self.raw_root.rglob("*.json"))
            if self.observations_path.is_file():
                paths.append(self.observations_path)
            for path in paths:
                content = path.read_bytes()
                matches += sum(content.count(value) for value in forbidden)
        if matches:
            violations.append("credential-like forbidden value persisted")
        return {
            "passed": not violations,
            "violations": violations,
            "observations": len(observations),
            "unique_raw_blobs": len(digests),
            "credential_persistence_matches": matches,
        }


def _calendar_url(
    *, credential: str, country: str, indicators: list[str], start: str, end: str
) -> str:
    if not credential or any(character.isspace() for character in credential):
        raise ValueError("invalid Trading Economics credential")
    indicator_path = quote(",".join(indicators), safe=",")
    country_path = quote(country, safe="")
    path = f"/calendar/country/{country_path}/indicator/{indicator_path}/{start}/{end}"
    return f"{TE_API_ROOT}{path}?{urlencode({'c': credential, 'f': 'json'})}"


def capture_authenticated_snapshot(
    store: VendorCaptureStore,
    *,
    rights_attestation_path: Path,
    country: str,
    indicators: list[str],
    start: str,
    end: str,
    timeout: float = 30.0,
) -> CaptureResult:
    """Capture one authenticated HTTPS response without persisting its credential."""
    license_class, rights = load_rights_attestation(rights_attestation_path)
    credential = os.environ.get("TRADING_ECONOMICS_API_KEY", "")
    if not credential:
        raise RuntimeError("TRADING_ECONOMICS_API_KEY is required")
    url = _calendar_url(
        credential=credential,
        country=country,
        indicators=indicators,
        start=start,
        end=end,
    )
    started = utc_now()
    try:
        request = Request(
            url,
            headers={"User-Agent": "macro-dislocation-lab/0.4 vendor-capture"},
        )
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = int(response.status)
    except HTTPError as exc:
        raise RuntimeError(
            f"Trading Economics returned HTTP {exc.code} from {public_endpoint(url)}"
        ) from None
    except Exception as exc:
        raise RuntimeError(
            f"Trading Economics request failed at {public_endpoint(url)}: "
            f"{type(exc).__name__}"
        ) from None
    if credential.encode("utf-8") in payload:
        raise RuntimeError("vendor response reflected the configured credential")
    received = utc_now()
    return store.capture(
        payload,
        provider="trading_economics",
        transport="https_snapshot",
        endpoint=url,
        request_started_at=started,
        received_at=received,
        received_monotonic_ns=time.monotonic_ns(),
        http_status=status,
        license_class=license_class,
        rights_profile=rights,
        provenance="authenticated_api_snapshot",
    )


def capture_stream_jsonl(
    store: VendorCaptureStore,
    lines: Iterable[str],
    *,
    rights_attestation_path: Path,
    endpoint: str = "wss://stream.tradingeconomics.com/",
) -> list[CaptureResult]:
    """Capture JSONL messages emitted by an authenticated calendar stream client."""
    license_class, rights = load_rights_attestation(rights_attestation_path)
    if not os.environ.get("TRADING_ECONOMICS_API_KEY"):
        raise RuntimeError("TRADING_ECONOMICS_API_KEY is required")
    results: list[CaptureResult] = []
    credential = os.environ.get("TRADING_ECONOMICS_API_KEY", "")
    wait_started = utc_now()
    for line in lines:
        received = utc_now()
        if not line.strip():
            wait_started = received
            continue
        if credential in line:
            raise RuntimeError("stream message reflected the configured credential")
        results.append(
            store.capture(
                line.encode("utf-8"),
                provider="trading_economics",
                transport="websocket_calendar",
                endpoint=endpoint,
                request_started_at=wait_started,
                received_at=received,
                received_monotonic_ns=time.monotonic_ns(),
                http_status=None,
                license_class=license_class,
                rights_profile=rights,
                provenance="authenticated_calendar_stream",
            )
        )
        wait_started = utc_now()
    return results
