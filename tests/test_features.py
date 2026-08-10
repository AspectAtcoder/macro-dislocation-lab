from __future__ import annotations

import unittest

from macro_dislocation.features import FeatureTransformer, Observation


def observation(event_id: str, event_type: str, value: float) -> Observation:
    return Observation(
        event_id=event_id,
        event_type=event_type,
        release_timestamp_utc="2024-01-01T00:00:00+00:00",
        initial_move_bps=value,
        primary_surprise=value,
        core_cpi_surprise=value if event_type == "CPI" else None,
        ahe_surprise=value if event_type == "NFP" else None,
        unemployment_bullish_surprise=value if event_type == "NFP" else None,
        target_return_bps=value,
        entry_mid=100.0,
        entry_bid=99.99,
        entry_ask=100.01,
        exit_mid=100.0,
        exit_bid=99.99,
        exit_ask=100.01,
    )


class FeatureTests(unittest.TestCase):
    def test_same_transform_is_reused_after_fit(self) -> None:
        rows = [
            observation("c1", "CPI", -1.0),
            observation("c2", "CPI", 1.0),
            observation("n1", "NFP", -2.0),
            observation("n2", "NFP", 2.0),
        ]
        transformer = FeatureTransformer().fit(rows)
        first = transformer.transform_one(rows[0])
        second = transformer.transform([rows[0]])[0]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertIn("primary:CPI", transformer.as_dict()["scales"])


if __name__ == "__main__":
    unittest.main()
