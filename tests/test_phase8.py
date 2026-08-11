from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase8 import run_phase8


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def arguments(output: Path) -> tuple[Path, ...]:
    return (
        PROJECT_ROOT / "config/phase8_trial_001.json",
        PROJECT_ROOT / "config/capture_authorization_contract.json",
        PROJECT_ROOT / "config/phase6_trial_001.json",
        PROJECT_ROOT / "config/phase6_campaign_roster_001.json",
        PROJECT_ROOT / "config/phase4_trial_001.json",
        PROJECT_ROOT / "config/vendor_rights_attestation.schema.json",
        PROJECT_ROOT / "config/phase7_trial_001.json",
        output,
    )


class Phase8Tests(unittest.TestCase):
    def test_registered_authorization_drill_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            first = run_phase8(*arguments(output), project_root=PROJECT_ROOT)
            second = run_phase8(*arguments(output), project_root=PROJECT_ROOT)
            self.assertTrue(all(first["pipeline_checks"].values()))
            self.assertEqual(first["activation_packet"], second["activation_packet"])
            self.assertEqual(first["failure_injections"], second["failure_injections"])

    def test_missed_window_never_claims_receipt_or_price_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = run_phase8(
                *arguments(Path(directory) / "output"), project_root=PROJECT_ROOT
            )
            self.assertEqual(summary["counts"]["access_receipts_issued"], 0)
            self.assertEqual(summary["counts"]["capture_permits_issued"], 0)
            self.assertFalse(summary["authenticated_vendor_request_executed"])
            self.assertFalse(summary["market_price_join_executed"])
            self.assertFalse(summary["price_model_executed"])


if __name__ == "__main__":
    unittest.main()
