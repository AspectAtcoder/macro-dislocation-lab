from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from macro_dislocation.phase2 import vendor_preflight


class Phase2Tests(unittest.TestCase):
    def test_guest_410_is_recorded_without_empirical_rows(self) -> None:
        error = HTTPError(
            "https://example.test",
            410,
            "Gone",
            {},
            io.BytesIO(b"guest discontinued"),
        )
        with patch("macro_dislocation.phase2.urlopen", side_effect=error):
            result = vendor_preflight()
        self.assertEqual(result["guest_http_status"], 410)
        self.assertEqual(result["empirical_vendor_rows_acquired"], 0)
        self.assertFalse(result["authenticated_probe_attempted"])


if __name__ == "__main__":
    unittest.main()
