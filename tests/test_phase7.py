from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase7 import run_phase7


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def arguments(output: Path) -> tuple[Path, ...]:
    return (
        PROJECT_ROOT / "config/phase7_trial_001.json",
        PROJECT_ROOT / "config/activation_handoff_contract.json",
        PROJECT_ROOT / "config/phase6_trial_001.json",
        PROJECT_ROOT / "config/phase6_campaign_roster_001.json",
        PROJECT_ROOT / "config/phase4_trial_001.json",
        PROJECT_ROOT / "tests/fixtures/phase7_component_binding.json",
        output,
    )


class Phase7Tests(unittest.TestCase):
    def test_registered_handoff_drill_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            first = run_phase7(*arguments(output), project_root=PROJECT_ROOT)
            second = run_phase7(*arguments(output), project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(
                first["handoff"]["handoff_hash"], second["handoff"]["handoff_hash"]
            )
            self.assertEqual(first["counts"]["shadow_release_plans"], 1)

    def test_synthetic_handoff_never_authorizes_external_or_price_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_phase7(
                *arguments(Path(directory) / "output"), project_root=PROJECT_ROOT
            )
            self.assertEqual(summary["counts"]["executable_handoffs"], 0)
            self.assertIsNone(summary["handoff"]["execution_permit"])
            self.assertFalse(summary["authenticated_vendor_request_executed"])
            self.assertFalse(summary["market_price_join_executed"])
            self.assertFalse(summary["price_model_executed"])


if __name__ == "__main__":
    unittest.main()
