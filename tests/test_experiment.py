from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from macro_dislocation.experiment import HORIZONS, event_metrics, resolve_targets, summarize
from macro_dislocation.models import Quote, Target


class ExperimentTests(unittest.TestCase):
    def test_strict_pre_release_and_first_after(self) -> None:
        event_time = datetime(2024, 1, 1, 13, 30, tzinfo=UTC)
        quotes = [
            Quote(event_time - timedelta(milliseconds=10), 99.99, 100.01),
            Quote(event_time, 100.99, 101.01),
            Quote(event_time + timedelta(seconds=1), 101.99, 102.01),
        ]
        targets = [
            Target(event_time, "e", "t0", "before"),
            Target(event_time + timedelta(seconds=1), "e", "h1", "after"),
        ]
        resolved = resolve_targets(quotes, targets)
        self.assertEqual(resolved[("e", "t0")].mid, 100.0)
        self.assertEqual(resolved[("e", "h1")].mid, 102.0)

    def test_completion_and_cost_are_separate(self) -> None:
        event = {
            "event_id": "e",
            "event_type": "CPI",
            "release_timestamp_utc": "2024-01-01T13:30:00+00:00",
        }
        base_time = datetime(2024, 1, 1, 13, 30, tzinfo=UTC)
        points = {"t0": Quote(base_time, 99.99, 100.01)}
        for horizon in HORIZONS:
            mid = 101.0 if horizon < 3600 else 102.0
            points[f"h{horizon}"] = Quote(
                base_time + timedelta(seconds=horizon), mid - 0.01, mid + 0.01
            )
        rows = event_metrics(event, points, min_final_move_bps=2.0)
        five = next(row for row in rows if row["horizon_seconds"] == 300)
        self.assertAlmostEqual(float(five["completion_ratio"]), 0.5, places=3)
        self.assertEqual(five["residual_continues_initial"], 1)
        self.assertLess(float(five["long_residual_net_bps"]), float(five["residual_to_final_bps"]))
        summary = summarize(rows)
        self.assertEqual(summary["screen"]["jump_capture_at_5m"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
