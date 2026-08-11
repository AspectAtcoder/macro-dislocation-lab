from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase5 import run_phase5


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def arguments(output: Path) -> tuple[Path, ...]:
    return (
        PROJECT_ROOT / "config/phase5_trial_001.json",
        PROJECT_ROOT / "config/empirical_evidence_contract.json",
        PROJECT_ROOT / "config/vendor_capture_contract.json",
        PROJECT_ROOT / "config/shadow_campaign_contract.json",
        PROJECT_ROOT / "tests/fixtures/phase5_release_schedule.json",
        PROJECT_ROOT / "tests/fixtures/phase5_trace_linked.json",
        PROJECT_ROOT / "tests/fixtures/phase5_te_pre_release.json",
        PROJECT_ROOT / "tests/fixtures/phase5_te_post_release.json",
        output,
    )


class Phase5Tests(unittest.TestCase):
    def test_registered_offline_enrollment_drill_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            first = run_phase5(*arguments(output), project_root=PROJECT_ROOT)
            second = run_phase5(*arguments(output), project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(
                first["evidence_package"]["package_hash"],
                second["evidence_package"]["package_hash"],
            )
            self.assertEqual(first["counts"]["capture_observations"], 2)
            self.assertEqual(first["counts"]["empirical_windows_enrolled"], 0)

    def test_partial_existing_capture_store_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            store = output / "capture_store"
            store.mkdir(parents=True)
            observation = store / "observations.jsonl"
            observation.write_text('{"partial":true}\n', encoding="utf-8")
            before = observation.read_bytes()
            with self.assertRaises(ValueError):
                run_phase5(*arguments(output), project_root=PROJECT_ROOT)
            self.assertEqual(observation.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
