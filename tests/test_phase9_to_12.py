from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.phase9 import run_phase9
from macro_dislocation.phase10 import run_phase10
from macro_dislocation.phase11 import run_phase11
from macro_dislocation.phase11 import run_registered_backtest
from macro_dislocation.phase12 import run_phase12
from macro_dislocation.verify_phase9 import verify_phase9
from macro_dislocation.verify_phase10 import verify_phase10
from macro_dislocation.verify_phase11 import verify_phase11
from macro_dislocation.verify_phase12 import verify_phase12

from tests.pipeline_helpers import ROOT


class Phase9To12Tests(unittest.TestCase):
    def test_phase9_registered_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_phase9(ROOT / "config/phase9_trial_001.json", ROOT / "config/phase8_trial_001.json", ROOT / "config/phase6_campaign_roster_001.json", Path(directory), project_root=ROOT)
            self.assertEqual(result["decision"], "READY_FOR_PROSPECTIVE_CAMPAIGN_ORCHESTRATION")

    def test_phase10_registered_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_phase10(ROOT / "config/phase10_trial_001.json", ROOT / "config/phase10_synthetic_events.csv", ROOT / "config/phase9_trial_001.json", Path(directory), project_root=ROOT)
            self.assertEqual(result["counts"]["labeled_rows"], 72)

    def test_phase11_registered_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_phase10(ROOT / "config/phase10_trial_001.json", ROOT / "config/phase10_synthetic_events.csv", ROOT / "config/phase9_trial_001.json", root / "p10", project_root=ROOT)
            result = run_phase11(ROOT / "config/phase11_trial_001.json", ROOT / "config/phase10_trial_001.json", root / "p10/labeled_events.csv", root / "p11", project_root=ROOT)
            self.assertEqual(result["counts"]["oos_predictions"], 12)

    def test_phase12_registered_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_phase10(ROOT / "config/phase10_trial_001.json", ROOT / "config/phase10_synthetic_events.csv", ROOT / "config/phase9_trial_001.json", root / "p10", project_root=ROOT)
            run_phase11(ROOT / "config/phase11_trial_001.json", ROOT / "config/phase10_trial_001.json", root / "p10/labeled_events.csv", root / "p11", project_root=ROOT)
            result = run_phase12(ROOT / "config/phase12_trial_001.json", ROOT / "config/phase11_trial_001.json", root / "p10/labeled_events.csv", root / "p11/model.json", root / "p12", project_root=ROOT)
            self.assertEqual(result["counts"]["live_orders"], 0)

    def test_phase9_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_phase9(Path(directory), ROOT / "config/phase9_trial_001.json", ROOT / "config/phase8_trial_001.json", ROOT / "config/phase6_campaign_roster_001.json", ROOT / "config/trial_registry.csv", project_root=ROOT, run_test_suite=False)
            self.assertFalse(result["passed"])

    def test_phase10_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_phase10(Path(directory), ROOT / "config/phase10_trial_001.json", ROOT / "config/phase10_synthetic_events.csv", ROOT / "config/phase9_trial_001.json", ROOT / "config/trial_registry.csv", project_root=ROOT, run_test_suite=False)
            self.assertFalse(result["passed"])

    def test_phase11_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_phase11(Path(directory), ROOT / "config/phase11_trial_001.json", ROOT / "config/phase10_trial_001.json", Path(directory) / "labels.csv", ROOT / "config/trial_registry.csv", project_root=ROOT, run_test_suite=False)
            self.assertFalse(result["passed"])

    def test_phase12_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = verify_phase12(Path(directory), ROOT / "config/phase12_trial_001.json", ROOT / "config/phase11_trial_001.json", Path(directory) / "labels.csv", Path(directory) / "model.json", ROOT / "config/trial_registry.csv", project_root=ROOT, run_test_suite=False)
            self.assertFalse(result["passed"])

    def test_registered_backtest_refuses_uncommitted_specification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specification = root / "spec.json"
            specification.write_text(
                (ROOT / "config/phase11_trial_001.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "inside the repository"):
                run_registered_backtest(
                    specification,
                    root / "labels.csv",
                    ROOT / "config/trial_registry.csv",
                    root / "output",
                    project_root=ROOT,
                )

    def test_registered_backtest_writes_reproducibility_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_phase10(
                ROOT / "config/phase10_trial_001.json",
                ROOT / "config/phase10_synthetic_events.csv",
                ROOT / "config/phase9_trial_001.json",
                root / "p10",
                project_root=ROOT,
            )
            result = run_registered_backtest(
                ROOT / "config/phase11_trial_001.json",
                root / "p10/labeled_events.csv",
                ROOT / "config/trial_registry.csv",
                root / "backtest",
                project_root=ROOT,
            )
            manifest = json.loads(
                (root / "backtest/manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "REGISTERED_BACKTEST_COMPLETE")
            self.assertEqual(manifest["trial"]["registered_commit"], "2606a58")
            self.assertEqual(manifest["model_hash"], result["model_hash"])


if __name__ == "__main__":
    unittest.main()
