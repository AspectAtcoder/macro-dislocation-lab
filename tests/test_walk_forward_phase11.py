from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.walk_forward import (
    backtest_metrics,
    deflated_sharpe_ratio,
    fit_model,
    predict_model,
    validate_backtest_policy,
    walk_forward_backtest,
    load_labeled_rows,
)
from macro_dislocation.pit_prices import write_csv

from tests.pipeline_helpers import backtest_rows, spec


SPEC = spec(11)


class WalkForwardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = backtest_rows()

    def test_registered_walk_forward_has_twelve_predictions(self) -> None:
        predictions, _ = walk_forward_backtest(self.rows, SPEC)
        self.assertEqual(len(predictions), 12)

    def test_every_fit_uses_past_only(self) -> None:
        predictions, _ = walk_forward_backtest(self.rows, SPEC)
        self.assertTrue(all(row["train_last_scheduled_at"] < row["scheduled_at"] for row in predictions))

    def test_final_model_uses_all_backtest_rows(self) -> None:
        _, model = walk_forward_backtest(self.rows, SPEC)
        self.assertEqual(model["training_events"], 24)
        self.assertEqual(model["training_dataset_roles"], ["backtest"])

    def test_model_hash_tamper_is_rejected(self) -> None:
        model = fit_model(self.rows, SPEC["features"], 1.0)
        model["coefficients"][0] += 1.0
        with self.assertRaisesRegex(ValueError, "model_hash_mismatch"):
            predict_model(model, self.rows[0])

    def test_sixth_feature_is_rejected(self) -> None:
        self.assertIn("feature_limit_exceeded", validate_backtest_policy(SPEC, feature_count=6))

    def test_future_fit_is_rejected(self) -> None:
        self.assertIn("walk_forward_leakage", validate_backtest_policy(SPEC, feature_count=5, train_last="2025-01-02", predict_at="2025-01-01"))

    def test_unregistered_trial_is_rejected(self) -> None:
        self.assertIn("trial_not_registered", validate_backtest_policy(SPEC, feature_count=5, trial_registered=False))

    def test_forward_role_is_rejected(self) -> None:
        self.assertIn("dataset_role_leakage", validate_backtest_policy(SPEC, feature_count=5, dataset_role="forward"))

    def test_metrics_include_dynamic_cost_losses(self) -> None:
        predictions, _ = walk_forward_backtest(self.rows, SPEC)
        metrics = backtest_metrics(predictions, 1)
        self.assertLess(metrics["total_net_bp"], 0.0)
        self.assertLess(metrics["event_sharpe"], 0.0)

    def test_deflated_sharpe_is_probability(self) -> None:
        value = deflated_sharpe_ratio([1.0, -0.5, 0.4, 0.2, -0.1], 3)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_single_trial_and_five_features_are_frozen(self) -> None:
        self.assertEqual(SPEC["model"]["trials_allowed"], 1)
        self.assertEqual(len(SPEC["features"]), 5)

    def test_loaded_labels_recompute_dynamic_costs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            write_csv(path, self.rows)
            loaded = load_labeled_rows(path, horizon=900, role="backtest")
            self.assertEqual(len(loaded), 24)

    def test_tampered_cost_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            write_csv(path, self.rows)
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["long_net_bp"] = str(float(rows[0]["long_net_bp"]) + 1.0)
            write_csv(path, rows)
            with self.assertRaisesRegex(ValueError, "label_cost_or_price_mismatch"):
                load_labeled_rows(path, horizon=900, role="backtest")

    def test_missing_evidence_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            rows = [dict(row) for row in self.rows]
            rows[0]["evidence_package_id"] = ""
            write_csv(path, rows)
            with self.assertRaisesRegex(ValueError, "missing_evidence_package_id"):
                load_labeled_rows(path, horizon=900, role="backtest")


if __name__ == "__main__":
    unittest.main()
