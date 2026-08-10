from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.verify import verify_phase0


class VerifyTests(unittest.TestCase):
    def test_missing_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specification = root / "spec.json"
            registry = root / "trials.csv"
            specification.write_text(json.dumps({"trial_id": "x"}), encoding="utf-8")
            registry.write_text("trial_id\nx\n", encoding="utf-8")
            result = verify_phase0(
                root / "missing", specification, registry, project_root=root
            )
            self.assertFalse(result["passed"])
            self.assertTrue(any("missing output" in failure for failure in result["failures"]))


if __name__ == "__main__":
    unittest.main()
