from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from macro_dislocation.calendar_data import normalize_calendar, parse_number


class CalendarTests(unittest.TestCase):
    def test_number_parser(self) -> None:
        self.assertEqual(parse_number("216K"), 216.0)
        self.assertEqual(parse_number("3.7%"), 3.7)
        self.assertIsNone(parse_number(""))

    def test_uses_bls_time_and_bundles_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.csv"
            schedule = root / "schedule.csv"
            output = root / "events.csv"
            raw.write_text(
                "DateTime,Currency,Impact,Event,Actual,Forecast,Previous,Detail\n"
                "2024-03-12T00:00:00+03:30,USD,High,CPI m/m,0.4%,0.3%,0.3%,x\n"
                "2024-03-12T17:00:00+03:30,USD,High,Core CPI m/m,0.4%,0.3%,0.4%,x\n",
                encoding="utf-8",
            )
            schedule.write_text(
                "release_date_et,release_time_et,event_type,reference_period,source_url\n"
                "2024-03-12,08:30,CPI,2024-02,https://example.test/bls\n",
                encoding="utf-8",
            )
            result = normalize_calendar(
                raw, schedule, output, consensus_source_url="https://example.test/calendar"
            )
            self.assertEqual(result["events"], 1)
            with output.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["release_timestamp_utc"], "2024-03-12T12:30:00+00:00")
            self.assertEqual(row["cpi_mom_actual_pct"], "0.4")
            self.assertEqual(row["core_cpi_mom_actual_pct"], "0.4")


if __name__ == "__main__":
    unittest.main()
