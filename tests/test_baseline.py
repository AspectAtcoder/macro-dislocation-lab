from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from macro_dislocation.baseline import fit_ridge, predict, run_baseline
from macro_dislocation.phase0 import audit_inputs


class BaselineTests(unittest.TestCase):
    def test_ridge_solver_recovers_unpenalized_line(self) -> None:
        features = [[-1.0], [0.0], [1.0], [2.0]]
        targets = [-1.0, 2.0, 5.0, 8.0]
        coefficients = fit_ridge(features, targets, alpha=0.0)
        self.assertAlmostEqual(coefficients[0], 2.0)
        self.assertAlmostEqual(coefficients[1], 3.0)
        self.assertEqual([round(value) for value in predict(coefficients, [[3.0]])], [11])

    def test_registered_pipeline_writes_twelve_test_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events_path = root / "events.csv"
            metrics_path = root / "metrics.csv"
            specification_path = root / "spec.json"
            event_fields = [
                "event_id", "event_type", "release_timestamp_utc",
                "cpi_mom_actual_pct", "cpi_mom_forecast_pct",
                "core_cpi_mom_actual_pct", "core_cpi_mom_forecast_pct",
                "nfp_change_actual_k", "nfp_change_forecast_k",
                "average_hourly_earnings_mom_actual_pct",
                "average_hourly_earnings_mom_forecast_pct",
                "unemployment_rate_actual_pct", "unemployment_rate_forecast_pct",
            ]
            metric_fields = [
                "event_id", "horizon_seconds", "horizon_mid", "spread_pips",
                "cumulative_return_bps",
            ]
            events = []
            metrics = []
            start = datetime(2024, 1, 1, tzinfo=UTC)
            for index in range(24):
                event_type = "CPI" if index % 2 == 0 else "NFP"
                event_id = f"e{index:02d}"
                signal = float((index % 6) - 2.5)
                row = {field: "" for field in event_fields}
                row.update(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "release_timestamp_utc": (start + timedelta(days=index)).isoformat(),
                    }
                )
                if event_type == "CPI":
                    row.update(
                        {
                            "cpi_mom_actual_pct": str(0.3 + signal / 100),
                            "cpi_mom_forecast_pct": "0.3",
                            "core_cpi_mom_actual_pct": str(0.3 + signal / 100),
                            "core_cpi_mom_forecast_pct": "0.3",
                        }
                    )
                else:
                    row.update(
                        {
                            "nfp_change_actual_k": str(200 + signal * 10),
                            "nfp_change_forecast_k": "200",
                            "average_hourly_earnings_mom_actual_pct": str(0.3 + signal / 100),
                            "average_hourly_earnings_mom_forecast_pct": "0.3",
                            "unemployment_rate_actual_pct": str(4.0 - signal / 100),
                            "unemployment_rate_forecast_pct": "4.0",
                        }
                    )
                events.append(row)
                entry_mid = 100.0
                target = signal * 2.0
                exit_mid = entry_mid * (1.0 + target / 10_000.0)
                metrics.extend(
                    [
                        {
                            "event_id": event_id,
                            "horizon_seconds": "60",
                            "horizon_mid": str(entry_mid),
                            "spread_pips": "0.5",
                            "cumulative_return_bps": str(signal),
                        },
                        {
                            "event_id": event_id,
                            "horizon_seconds": "900",
                            "horizon_mid": str(exit_mid),
                            "spread_pips": "0.5",
                            "cumulative_return_bps": str(signal + target),
                        },
                    ]
                )
            with events_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=event_fields)
                writer.writeheader()
                writer.writerows(events)
            with metrics_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=metric_fields)
                writer.writeheader()
                writer.writerows(metrics)
            specification_path.write_text(
                json.dumps(
                    {
                        "trial_id": "test",
                        "sample": {"expected_events": 24},
                        "split": {"train_events": 12, "test_events": 12},
                        "timing": {"entry_seconds_after_release": 60, "exit_seconds_after_release": 900},
                        "model": {"alpha": 1.0},
                        "cost": {"additional_roundtrip_slippage_pips": 1.0},
                        "trace_gate": {"minimum_test_sign_accuracy": 7 / 12},
                    }
                ),
                encoding="utf-8",
            )
            summary = run_baseline(
                events_path, metrics_path, specification_path, root / "output"
            )
            self.assertEqual(summary["test"]["events"], 12)
            with (root / "output" / "predictions.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 12)

    def test_input_audit_detects_valid_small_shape_as_non_phase0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / "events.csv"
            quotes = root / "quotes.csv"
            events.write_text(
                "event_id,event_type,cpi_mom_actual_pct,cpi_mom_forecast_pct,nfp_change_actual_k,nfp_change_forecast_k\n"
                "c,CPI,0.3,0.2,,\n",
                encoding="utf-8",
            )
            quotes.write_text(
                "timestamp_utc,bid,ask,source\n"
                "2024-01-01T00:00:00+00:00,100.0,100.01,test\n",
                encoding="utf-8",
            )
            audit = audit_inputs(events, quotes)
            self.assertFalse(audit["valid"])
            self.assertEqual(audit["quotes"]["crossed"], 0)


if __name__ == "__main__":
    unittest.main()
