from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify_phase2 import verify_phase2


class VerifyPhase2Tests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / name for name in ("spec.json", "contract.json", "calendar.csv", "documents.json", "fomc.csv", "eia.csv", "trials.csv")]
            files[0].write_text(json.dumps({"trial_id": "trial"}), encoding="utf-8")
            files[1].write_text("{}", encoding="utf-8")
            for path in files[2:]:
                path.write_text("", encoding="utf-8")
            result = verify_phase2(
                root / "missing",
                files[0],
                files[1],
                files[2],
                files[3],
                files[4],
                files[5],
                files[6],
                project_root=root,
                run_tests=False,
            )
            self.assertFalse(result["passed"])
            self.assertIn("missing output", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
