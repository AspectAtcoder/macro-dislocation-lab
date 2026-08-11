from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify_phase5 import verify_phase5


class VerifyPhase5Tests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = (
                "spec.json",
                "evidence.json",
                "capture.json",
                "campaign.json",
                "schedule.json",
                "trace.json",
                "pre.json",
                "post.json",
                "trials.csv",
            )
            files = [root / name for name in names]
            files[0].write_text(json.dumps({"trial_id": "trial"}), encoding="utf-8")
            for path in files[1:8]:
                path.write_text("{}", encoding="utf-8")
            files[8].write_text("trial_id,registered_commit\n", encoding="utf-8")
            result = verify_phase5(
                root / "missing",
                *files,
                project_root=root,
                run_tests=False,
            )
            self.assertFalse(result["passed"])
            self.assertIn("missing output", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
