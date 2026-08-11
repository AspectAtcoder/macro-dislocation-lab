from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc
GENESIS_HASH = "0" * 64


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("campaign timestamp must be offset-aware")
    return parsed.astimezone(UTC)


def campaign_event_hash(event: dict[str, Any]) -> str:
    core = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(_canonical(core)).hexdigest()


def seal_campaign_event(event: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(event)
    sealed["event_hash"] = campaign_event_hash(sealed)
    return sealed


def replay_campaign(
    events: Iterable[dict[str, Any]], specification: dict[str, Any]
) -> dict[str, Any]:
    ordered_states = list(specification["state_order"])
    terminal = set(specification["terminal_states"])
    policy = specification["policy"]
    issues: list[str] = []
    state: str | None = None
    campaign_id: str | None = None
    source_event_id: str | None = None
    previous_hash = GENESIS_HASH
    previous_time: datetime | None = None
    count = 0
    for expected_sequence, event in enumerate(events, start=1):
        count += 1
        if event.get("event_hash") != campaign_event_hash(event):
            issues.append("campaign_event_hash_mismatch")
        if event.get("previous_hash") != previous_hash:
            issues.append("campaign_hash_chain_mismatch")
        if event.get("sequence") != expected_sequence:
            issues.append("campaign_sequence_mismatch")
        try:
            occurred = _parse_time(str(event.get("occurred_at") or ""))
        except ValueError:
            issues.append("campaign_timestamp_invalid")
            occurred = previous_time or datetime.min.replace(tzinfo=UTC)
        if previous_time is not None and occurred < previous_time:
            issues.append("campaign_clock_regression")
        previous_time = occurred
        if campaign_id is None:
            campaign_id = str(event.get("campaign_id") or "")
            source_event_id = str(event.get("source_event_id") or "")
        elif event.get("campaign_id") != campaign_id:
            issues.append("campaign_id_mismatch")
        if policy["require_source_event_binding"] and event.get(
            "source_event_id"
        ) != source_event_id:
            issues.append("campaign_source_event_mismatch")
        new_state = str(event.get("state") or "")
        if state is None:
            valid_transition = new_state == ordered_states[0]
        elif state in terminal:
            valid_transition = False
        elif new_state == "ABORTED" and policy["allow_abort_from_nonterminal"]:
            valid_transition = True
        else:
            try:
                valid_transition = (
                    ordered_states.index(new_state) == ordered_states.index(state) + 1
                )
            except ValueError:
                valid_transition = False
        if not valid_transition:
            issues.append("campaign_transition_invalid")
        if (
            policy["require_evidence_id_after_planning"]
            and new_state != "PLANNED"
            and not str(event.get("evidence_id") or "").strip()
        ):
            issues.append("campaign_evidence_required")
        state = new_state
        previous_hash = str(event.get("event_hash") or "")
    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "campaign_id": campaign_id,
        "source_event_id": source_event_id,
        "events": count,
        "state": state,
        "terminal": state in terminal,
        "head_hash": previous_hash,
    }


class CampaignJournal:
    def __init__(self, path: Path, specification: dict[str, Any]):
        self.path = path
        self.specification = specification

    def events(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        output: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    raise ValueError(f"torn campaign journal line: {number}")
                output.append(json.loads(line))
        return output

    def append(
        self,
        *,
        campaign_id: str,
        source_event_id: str,
        state: str,
        occurred_at: str,
        evidence_id: str | None,
        provenance: str,
    ) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path, os.O_RDWR | os.O_CREAT, 0o600
        )
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
                raise ValueError("torn campaign journal line")
            current = [json.loads(line) for line in raw.splitlines() if line]
            previous_hash = current[-1]["event_hash"] if current else GENESIS_HASH
            event = seal_campaign_event(
                {
                    "sequence": len(current) + 1,
                    "campaign_id": campaign_id,
                    "source_event_id": source_event_id,
                    "state": state,
                    "occurred_at": _parse_time(occurred_at).isoformat(),
                    "evidence_id": evidence_id,
                    "provenance": provenance,
                    "previous_hash": previous_hash,
                }
            )
            audit = replay_campaign([*current, event], self.specification)
            if not audit["passed"]:
                raise ValueError(audit["issues"][0])
            line = json.dumps(
                event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            os.lseek(descriptor, 0, os.SEEK_END)
            written = 0
            while written < len(line):
                written += os.write(descriptor, line[written:])
            os.fsync(descriptor)
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return event
