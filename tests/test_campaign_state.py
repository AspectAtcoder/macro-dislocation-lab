from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.campaign_state import (
    CampaignJournal,
    replay_campaign,
    seal_campaign_event,
)

from tests.pipeline_helpers import spec


SPEC = spec(9)


def event(sequence: int, state: str, previous: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "sequence": sequence,
        "campaign_id": "campaign:test",
        "source_event_id": "source:test",
        "state": state,
        "occurred_at": f"2031-01-01T00:0{sequence}:00+00:00",
        "evidence_id": None if state == "PLANNED" else f"evidence:{sequence}",
        "provenance": "synthetic_fixture",
        "previous_hash": previous,
    }
    value.update(changes)
    return seal_campaign_event(value)


def valid_events() -> list[dict[str, object]]:
    output = []
    previous = "0" * 64
    for index, state in enumerate(SPEC["state_order"], start=1):
        item = event(index, state, previous)
        output.append(item)
        previous = str(item["event_hash"])
    return output


class CampaignStateTests(unittest.TestCase):
    def test_valid_campaign_reaches_enrolled(self) -> None:
        audit = replay_campaign(valid_events(), SPEC)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["state"], "EVIDENCE_ENROLLED")

    def test_out_of_order_transition_fails(self) -> None:
        rows = valid_events()[:2]
        rows[1] = event(2, "STREAM_COMPLETE", str(rows[0]["event_hash"]))
        self.assertIn("campaign_transition_invalid", replay_campaign(rows, SPEC)["issues"])

    def test_source_substitution_fails(self) -> None:
        rows = valid_events()[:2]
        rows[1] = event(2, "ACCESS_AUTHORIZED", str(rows[0]["event_hash"]), source_event_id="other")
        self.assertIn("campaign_source_event_mismatch", replay_campaign(rows, SPEC)["issues"])

    def test_clock_regression_fails(self) -> None:
        rows = valid_events()[:2]
        rows[1] = event(2, "ACCESS_AUTHORIZED", str(rows[0]["event_hash"]), occurred_at="2030-12-31T23:00:00+00:00")
        self.assertIn("campaign_clock_regression", replay_campaign(rows, SPEC)["issues"])

    def test_missing_evidence_fails(self) -> None:
        rows = valid_events()[:2]
        rows[1] = event(2, "ACCESS_AUTHORIZED", str(rows[0]["event_hash"]), evidence_id=None)
        self.assertIn("campaign_evidence_required", replay_campaign(rows, SPEC)["issues"])

    def test_hash_tamper_fails(self) -> None:
        rows = valid_events()
        rows[-1]["evidence_id"] = "changed"
        self.assertIn("campaign_event_hash_mismatch", replay_campaign(rows, SPEC)["issues"])

    def test_sequence_mismatch_fails(self) -> None:
        rows = valid_events()[:2]
        rows[1] = event(9, "ACCESS_AUTHORIZED", str(rows[0]["event_hash"]))
        self.assertIn("campaign_sequence_mismatch", replay_campaign(rows, SPEC)["issues"])

    def test_abort_is_terminal(self) -> None:
        first = valid_events()[0]
        aborted = event(2, "ABORTED", str(first["event_hash"]), evidence_id="error:1")
        self.assertTrue(replay_campaign([first, aborted], SPEC)["passed"])

    def test_resume_after_abort_fails(self) -> None:
        first = valid_events()[0]
        aborted = event(2, "ABORTED", str(first["event_hash"]), evidence_id="error:1")
        resumed = event(3, "ACCESS_AUTHORIZED", str(aborted["event_hash"]))
        self.assertIn("campaign_transition_invalid", replay_campaign([first, aborted, resumed], SPEC)["issues"])

    def test_journal_round_trip_and_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = CampaignJournal(Path(directory) / "events.jsonl", SPEC)
            previous = None
            for index, state in enumerate(SPEC["state_order"], start=1):
                previous = journal.append(campaign_id="campaign:test", source_event_id="source:test", state=state, occurred_at=f"2031-01-01T00:0{index}:00+00:00", evidence_id=None if state == "PLANNED" else f"evidence:{index}", provenance="synthetic_fixture")
            self.assertEqual(len(journal.events()), 6)
            self.assertEqual(journal.path.stat().st_mode & 0o777, 0o600)
            self.assertIsNotNone(previous)

    def test_journal_rejects_invalid_transition_without_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = CampaignJournal(Path(directory) / "events.jsonl", SPEC)
            journal.append(campaign_id="campaign:test", source_event_id="source:test", state="PLANNED", occurred_at="2031-01-01T00:00:00+00:00", evidence_id=None, provenance="synthetic_fixture")
            with self.assertRaisesRegex(ValueError, "campaign_transition_invalid"):
                journal.append(campaign_id="campaign:test", source_event_id="source:test", state="STREAM_COMPLETE", occurred_at="2031-01-01T00:01:00+00:00", evidence_id="evidence:x", provenance="synthetic_fixture")
            self.assertEqual(len(journal.events()), 1)

    def test_torn_journal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"broken":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "torn"):
                CampaignJournal(path, SPEC).events()


if __name__ == "__main__":
    unittest.main()
