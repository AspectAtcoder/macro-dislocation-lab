from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase6 import run_phase6


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def arguments(output: Path) -> tuple[Path, ...]:
    return (
        PROJECT_ROOT / "config/phase6_trial_001.json",
        PROJECT_ROOT / "config/campaign_roster_contract.json",
        PROJECT_ROOT / "config/phase6_campaign_roster_001.json",
        output,
    )


class Phase6Tests(unittest.TestCase):
    def test_registered_roster_drill_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            first = run_phase6(*arguments(output), project_root=PROJECT_ROOT)
            second = run_phase6(*arguments(output), project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(
                first["campaign_readiness"]["readiness_hash"],
                second["campaign_readiness"]["readiness_hash"],
            )
            self.assertEqual(first["counts"]["campaign_windows"], 6)

    def test_roster_run_never_claims_empirical_or_price_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_phase6(
                *arguments(Path(directory) / "output"), project_root=PROJECT_ROOT
            )
            self.assertEqual(summary["counts"]["empirical_windows_captured"], 0)
            self.assertFalse(summary["authenticated_vendor_request_executed"])
            self.assertFalse(summary["market_price_join_executed"])
            self.assertFalse(summary["price_model_executed"])


if __name__ == "__main__":
    unittest.main()
