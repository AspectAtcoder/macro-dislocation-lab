from __future__ import annotations

import lzma
import struct
import unittest
from datetime import UTC, datetime

from macro_dislocation.dukascopy import decode_bi5, hour_url


class DukascopyTests(unittest.TestCase):
    def test_decodes_big_endian_tick(self) -> None:
        raw = struct.pack(">3i2f", 1_250, 145_391, 145_386, 1.2, 3.4)
        hour = datetime(2024, 1, 11, 13, tzinfo=UTC)
        quotes = list(decode_bi5(lzma.compress(raw), hour, 1_000))
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].timestamp_utc.microsecond, 250_000)
        self.assertEqual(quotes[0].timestamp_utc.second, 1)
        self.assertAlmostEqual(quotes[0].ask, 145.391)
        self.assertAlmostEqual(quotes[0].bid, 145.386)

    def test_dukascopy_month_is_zero_indexed(self) -> None:
        hour = datetime(2024, 1, 11, 13, tzinfo=UTC)
        self.assertTrue(hour_url("USDJPY", hour).endswith("/2024/00/11/13h_ticks.bi5"))


if __name__ == "__main__":
    unittest.main()
