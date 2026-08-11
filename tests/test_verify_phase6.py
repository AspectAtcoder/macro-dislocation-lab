from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify_phase6 import verify_phase6


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VerifyPhase6Tests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_phase6(
                Path(directory),
                PROJECT_ROOT / "config/phase6_trial_001.json",
                PROJECT_ROOT / "config/campaign_roster_contract.json",
                PROJECT_ROOT / "config/phase6_campaign_roster_001.json",
                PROJECT_ROOT / "config/trial_registry.csv",
                project_root=PROJECT_ROOT,
                run_tests=False,
            )
            self.assertFalse(result["passed"])
            self.assertTrue(result["failures"])


if __name__ == "__main__":
    unittest.main()
