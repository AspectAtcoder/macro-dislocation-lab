from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase4 import run_phase4


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Phase4Tests(unittest.TestCase):
    def test_registered_offline_campaign_drill_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            arguments = (
                PROJECT_ROOT / "config/phase4_trial_001.json",
                PROJECT_ROOT / "config/shadow_campaign_contract.json",
                PROJECT_ROOT / "config/vendor_capture_contract.json",
                PROJECT_ROOT / "tests/fixtures/shadow_release_schedule.json",
                PROJECT_ROOT / "tests/fixtures/shadow_trace_pass.json",
                output,
            )
            first = run_phase4(*arguments, project_root=PROJECT_ROOT)
            second = run_phase4(*arguments, project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(first["audit_hash"], second["audit_hash"])
            self.assertEqual(first["counts"]["trace_events"], 20)
            self.assertEqual(first["counts"]["complete_empirical_windows"], 0)
            self.assertFalse(first["campaign_gate"]["promoted"])

    def test_partial_existing_trace_store_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            store = output / "shadow_trace_store"
            store.mkdir(parents=True)
            (store / "trace.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": "partial",
                        "plan_id": "partial",
                        "kind": "run_started",
                        "observed_at": "2030-01-10T13:27:45+00:00",
                        "received_monotonic_ns": 1,
                        "details": {"schedule_sha256": "partial"},
                        "event_id": "bad",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            before = (store / "trace.jsonl").read_bytes()
            with self.assertRaises(ValueError):
                run_phase4(
                    PROJECT_ROOT / "config/phase4_trial_001.json",
                    PROJECT_ROOT / "config/shadow_campaign_contract.json",
                    PROJECT_ROOT / "config/vendor_capture_contract.json",
                    PROJECT_ROOT / "tests/fixtures/shadow_release_schedule.json",
                    PROJECT_ROOT / "tests/fixtures/shadow_trace_pass.json",
                    output,
                    project_root=PROJECT_ROOT,
                )
            self.assertEqual((store / "trace.jsonl").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
