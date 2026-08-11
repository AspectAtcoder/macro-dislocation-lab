from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from macro_dislocation.pit_prices import (
    build_labels,
    dynamic_slippage_bp,
    generate_quotes,
    rows_csv_sha256,
    align_quote_tape,
    load_feature_events,
    load_quote_tape,
    validate_pit_inputs,
)

from tests.pipeline_helpers import events_labels, spec
from macro_dislocation.phase10 import build_empirical_pit_labels


SPEC = spec(10)


class PitPriceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.labels = events_labels()
        self.quotes = generate_quotes(self.events, SPEC)

    def test_registered_event_split(self) -> None:
        self.assertEqual(len(self.events), 36)
        self.assertEqual(sum(row.dataset_role == "backtest" for row in self.events), 24)
        self.assertEqual(sum(row.dataset_role == "forward" for row in self.events), 12)

    def test_three_quote_points_per_event(self) -> None:
        self.assertEqual(len(self.quotes), 108)
        self.assertEqual({row["horizon_seconds"] for row in self.quotes}, {60, 900, 3600})

    def test_two_labels_per_event(self) -> None:
        self.assertEqual(len(self.labels), 72)

    def test_feature_after_anchor_is_rejected(self) -> None:
        changed = list(self.events)
        changed[0] = replace(changed[0], feature_ready_at="2024-01-05T13:31:01+00:00")
        self.assertIn("feature_not_point_in_time", validate_pit_inputs(changed, self.quotes, SPEC))

    def test_stale_quote_is_rejected(self) -> None:
        quotes = json.loads(json.dumps(self.quotes))
        quotes[0]["quote_lag_seconds"] = 2.1
        self.assertIn("quote_lag_exceeded", validate_pit_inputs(self.events, quotes, SPEC))

    def test_crossed_market_is_rejected(self) -> None:
        quotes = json.loads(json.dumps(self.quotes))
        quotes[0]["bid"] = quotes[0]["ask"]
        self.assertIn("invalid_bid_ask", validate_pit_inputs(self.events, quotes, SPEC))

    def test_nonfinite_quote_is_rejected(self) -> None:
        quotes = json.loads(json.dumps(self.quotes))
        quotes[0]["bid"] = math.nan
        self.assertIn("nonfinite_numeric_value", validate_pit_inputs(self.events, quotes, SPEC))

    def test_duplicate_event_is_rejected(self) -> None:
        self.assertIn("duplicate_event_id", validate_pit_inputs([*self.events, self.events[0]], self.quotes, SPEC))

    def test_constant_cost_is_rejected(self) -> None:
        self.assertIn("constant_cost_forbidden", validate_pit_inputs(self.events, self.quotes, SPEC, cost_mode="constant"))

    def test_slippage_changes_with_spread_and_volatility(self) -> None:
        self.assertGreater(dynamic_slippage_bp(3.0, 8.0), dynamic_slippage_bp(1.0, 3.0))

    def test_midpoint_target_matches_fixture(self) -> None:
        first = next(row for row in self.labels if row["event_id"] == "SYN-2024-01-NFP" and row["exit_horizon_seconds"] == 900)
        self.assertAlmostEqual(first["target_mid_bp"], 4.9, places=9)

    def test_costs_can_overwhelm_correct_direction(self) -> None:
        first = next(row for row in self.labels if row["event_id"] == "SYN-2024-01-NFP" and row["exit_horizon_seconds"] == 900)
        self.assertLess(first["long_net_bp"], first["target_mid_bp"])

    def test_csv_digest_is_deterministic(self) -> None:
        self.assertEqual(rows_csv_sha256(self.quotes), rows_csv_sha256(self.quotes))

    def test_build_labels_is_deterministic(self) -> None:
        self.assertEqual(self.labels, build_labels(self.events, self.quotes, SPEC))

    def test_empirical_files_join_real_bid_ask_tape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features = root / "features.csv"
            features.write_text(
                "event_id,evidence_package_id,scheduled_at,event_family,feature_ready_at,headline_surprise,revision_surprise,internal_breadth,regime_score,pre_volatility_bp,dataset_role,provenance\n"
                "REAL-1,evidence:real-1,2031-01-01T13:30:00+00:00,CPI,2031-01-01T13:30:30+00:00,1,0,0.5,0.2,4,backtest,licensed_shadow\n",
                encoding="utf-8",
            )
            quotes = root / "quotes.csv"
            quotes.write_text(
                "timestamp,bid,ask,asset,provenance\n"
                "2031-01-01T13:31:00+00:00,149.99,150.01,USDJPY,licensed_tick\n"
                "2031-01-01T13:45:00+00:00,150.04,150.06,USDJPY,licensed_tick\n"
                "2031-01-01T14:30:00+00:00,150.09,150.11,USDJPY,licensed_tick\n",
                encoding="utf-8",
            )
            package = {
                "package_id": "evidence:real-1",
                "scheduled_at": "2031-01-01T13:30:00+00:00",
                "event_family": "CPI",
                "enrollable": True,
                "issues": [],
            }
            (root / "ledger").mkdir()
            (root / "ledger/evidence.jsonl").write_text(
                json.dumps(package) + "\n", encoding="utf-8"
            )
            with patch(
                "macro_dislocation.phase10.EvidenceLedger.packages",
                return_value=[package],
            ):
                result = build_empirical_pit_labels(
                    Path(__file__).resolve().parents[1]
                    / "config/phase10_trial_001.json",
                    features,
                    quotes,
                    root / "ledger",
                    root / "output",
                )
            self.assertEqual(result["events"], 1)
            self.assertEqual(result["labels"], 2)
            self.assertEqual(result["evidence_packages"], 1)

    def test_quote_tape_alignment_records_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features = root / "features.csv"
            features.write_text(
                "event_id,evidence_package_id,scheduled_at,event_family,feature_ready_at,headline_surprise,revision_surprise,internal_breadth,regime_score,pre_volatility_bp,dataset_role,provenance\n"
                "REAL-1,evidence:real-1,2031-01-01T13:30:00+00:00,CPI,2031-01-01T13:30:30+00:00,1,0,0.5,0.2,4,backtest,licensed_shadow\n",
                encoding="utf-8",
            )
            quotes = root / "quotes.csv"
            quotes.write_text(
                "timestamp,bid,ask,asset,provenance\n"
                "2031-01-01T13:31:00+00:00,149.99,150.01,USDJPY,licensed_tick\n"
                "2031-01-01T13:45:00+00:00,150.04,150.06,USDJPY,licensed_tick\n"
                "2031-01-01T14:30:00+00:00,150.09,150.11,USDJPY,licensed_tick\n",
                encoding="utf-8",
            )
            aligned = align_quote_tape(
                load_feature_events(features),
                load_quote_tape(quotes, asset="USDJPY"),
                SPEC,
            )
            self.assertEqual(len(aligned), 3)
            self.assertEqual({row["quote_provenance"] for row in aligned}, {"licensed_tick"})


if __name__ == "__main__":
    unittest.main()
