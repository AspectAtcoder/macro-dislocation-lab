from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase3 import run_phase3


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Phase3Tests(unittest.TestCase):
    def test_registered_offline_capture_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            arguments = (
                PROJECT_ROOT / "config/phase3_trial_001.json",
                PROJECT_ROOT / "config/vendor_capture_contract.json",
                PROJECT_ROOT / "config/pit_event_contract.json",
                output,
            )
            first = run_phase3(*arguments, project_root=PROJECT_ROOT)
            second = run_phase3(*arguments, project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(first["capture_hash"], second["capture_hash"])
            self.assertEqual(first["counts"]["capture_observations"], 3)
            self.assertEqual(first["counts"]["unique_raw_blobs"], 2)
            self.assertEqual(first["counts"]["empirical_vendor_rows"], 0)

    def test_partial_existing_store_is_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir(parents=True)
            store = output / "vendor_capture_store"
            store.mkdir()
            (store / "observations.jsonl").write_text(
                json.dumps(
                    {
                        "capture_id": "partial",
                        "provider": "x",
                        "transport": "synthetic_fixture",
                        "public_endpoint": "https://example.invalid",
                        "request_started_at": "2030-01-01T00:00:00+00:00",
                        "received_at": "2030-01-01T00:00:01+00:00",
                        "received_monotonic_ns": 1,
                        "http_status": None,
                        "payload_sha256": "a" * 64,
                        "payload_bytes": 1,
                        "license_class": "synthetic_fixture",
                        "rights_profile": {},
                        "provenance": "partial",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            before = (store / "observations.jsonl").read_bytes()
            with self.assertRaises(RuntimeError):
                run_phase3(
                    PROJECT_ROOT / "config/phase3_trial_001.json",
                    PROJECT_ROOT / "config/vendor_capture_contract.json",
                    PROJECT_ROOT / "config/pit_event_contract.json",
                    output,
                    project_root=PROJECT_ROOT,
                )
            self.assertEqual((store / "observations.jsonl").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
