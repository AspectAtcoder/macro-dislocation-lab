from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.forward_test import (
    ForwardJournal,
    journal_risk_state,
    record_paper_signal,
    replay_forward_events,
    risk_issues,
    settle_paper_signal,
)
from macro_dislocation.phase12 import signal_input_from_label

from tests.pipeline_helpers import final_model, forward_rows, spec


SPEC = spec(12)
PHASE11 = spec(11)


class ForwardTestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = final_model()
        self.row = forward_rows()[0]
        self.signal_input = signal_input_from_label(self.row)

    def base_risk(self) -> dict[str, object]:
        return {
            "now": self.row["entry_timestamp"],
            "quote_timestamp": self.row["entry_timestamp"],
            "bid": float(self.row["entry_bid"]),
            "ask": float(self.row["entry_ask"]),
            "open_positions": 0,
            "daily_pnl_bp": 0.0,
            "kill_switch": False,
            "policy": SPEC["policy"],
        }

    def test_kill_switch_blocks(self) -> None:
        self.assertIn("kill_switch_active", risk_issues(**{**self.base_risk(), "kill_switch": True}))

    def test_stale_quote_blocks(self) -> None:
        self.assertIn("forward_quote_stale", risk_issues(**{**self.base_risk(), "quote_timestamp": "2025-01-10T13:30:50+00:00"}))

    def test_wide_spread_blocks(self) -> None:
        self.assertIn("forward_spread_too_wide", risk_issues(**{**self.base_risk(), "ask": float(self.row["entry_bid"]) * 1.002}))

    def test_position_limit_blocks(self) -> None:
        self.assertIn("forward_position_limit", risk_issues(**{**self.base_risk(), "open_positions": 1}))

    def test_daily_loss_limit_blocks(self) -> None:
        self.assertIn("daily_loss_limit_reached", risk_issues(**{**self.base_risk(), "daily_pnl_bp": -40.0}))

    def test_signal_rejects_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = dict(self.signal_input)
            value["target_mid_bp"] = 1.0
            with self.assertRaisesRegex(ValueError, "forward_outcome_leakage"):
                record_paper_signal(ForwardJournal(Path(directory) / "journal.jsonl"), self.model, value, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=2.0)

    def test_signal_then_settlement_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            signal = record_paper_signal(journal, self.model, self.signal_input, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=2.0)
            settle_paper_signal(journal, signal["payload"]["signal_id"], occurred_at=self.row["exit_timestamp"], exit_bid=float(self.row["exit_bid"]), exit_ask=float(self.row["exit_ask"]), provenance="synthetic_fixture")
            audit = replay_forward_events(journal.events())
            self.assertTrue(audit["passed"])
            self.assertEqual(audit["open_signals"], 0)

    def test_early_settlement_rejected_without_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            signal = record_paper_signal(journal, self.model, self.signal_input, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=2.0)
            with self.assertRaisesRegex(ValueError, "forward_settlement_too_early"):
                settle_paper_signal(journal, signal["payload"]["signal_id"], occurred_at=self.row["entry_timestamp"], exit_bid=float(self.row["exit_bid"]), exit_ask=float(self.row["exit_ask"]), provenance="synthetic_fixture")
            self.assertEqual(len(journal.events()), 1)

    def test_journal_tamper_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            record_paper_signal(journal, self.model, self.signal_input, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=2.0)
            events = journal.events()
            events[0]["payload"]["forecast_target_bp"] = 999.0
            self.assertIn("forward_event_hash_mismatch", replay_forward_events(events)["issues"])

    def test_journal_risk_state_counts_open_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            signal = record_paper_signal(journal, self.model, self.signal_input, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=0.0)
            state = journal_risk_state(journal.events(), self.row["entry_timestamp"])
            self.assertEqual(state["open_positions"], int(signal["payload"]["position"] != 0))

    def test_signal_position_limit_is_rechecked_inside_journal_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            record_paper_signal(
                journal,
                self.model,
                self.signal_input,
                now=self.row["entry_timestamp"],
                policy=SPEC["policy"],
                kill_switch=False,
                trade_threshold_bp=0.0,
            )
            with self.assertRaisesRegex(ValueError, "forward_position_limit"):
                record_paper_signal(
                    journal,
                    self.model,
                    self.signal_input,
                    now=self.row["entry_timestamp"],
                    policy=SPEC["policy"],
                    kill_switch=False,
                    trade_threshold_bp=0.0,
                )
            self.assertEqual(len(journal.events()), 1)

    def test_settlement_is_paper_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = ForwardJournal(Path(directory) / "journal.jsonl")
            signal = record_paper_signal(journal, self.model, self.signal_input, now=self.row["entry_timestamp"], policy=SPEC["policy"], kill_switch=False, trade_threshold_bp=2.0)
            settlement = settle_paper_signal(journal, signal["payload"]["signal_id"], occurred_at=self.row["exit_timestamp"], exit_bid=float(self.row["exit_bid"]), exit_ask=float(self.row["exit_ask"]), provenance="synthetic_fixture")
            self.assertEqual(signal["payload"]["mode"], "paper_only")
            self.assertEqual(settlement["payload"]["mode"], "paper_only")

    def test_torn_journal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            path.write_text('{"broken":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "torn"):
                ForwardJournal(path).events()


if __name__ == "__main__":
    unittest.main()
