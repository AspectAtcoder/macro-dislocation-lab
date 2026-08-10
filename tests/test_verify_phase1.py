from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify_phase1 import verify_phase1


class VerifyPhase1Tests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specification = root / "spec.json"
            axes = root / "axes.json"
            registry = root / "trials.csv"
            specification.write_text(json.dumps({"trial_id": "trial"}))
            axes.write_text(json.dumps({"axes": {}}))
            registry.write_text("trial_id,registered_commit\n")
            result = verify_phase1(
                root / "missing",
                root / "store",
                specification,
                axes,
                registry,
                project_root=root,
                run_tests=False,
            )
            self.assertFalse(result["passed"])
            self.assertIn("missing output", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
