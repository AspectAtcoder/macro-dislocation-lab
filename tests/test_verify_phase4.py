from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify_phase4 import verify_phase4


class VerifyPhase4Tests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [
                root / name
                for name in (
                    "spec.json",
                    "campaign.json",
                    "capture.json",
                    "schedule.json",
                    "trace.json",
                    "trials.csv",
                )
            ]
            files[0].write_text(json.dumps({"trial_id": "trial"}), encoding="utf-8")
            for path in files[1:5]:
                path.write_text("{}", encoding="utf-8")
            files[5].write_text("trial_id,registered_commit\n", encoding="utf-8")
            result = verify_phase4(
                root / "missing",
                files[0],
                files[1],
                files[2],
                files[3],
                files[4],
                files[5],
                project_root=root,
                run_tests=False,
            )
            self.assertFalse(result["passed"])
            self.assertIn("missing output", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
