from __future__ import annotations

import unittest

from macro_dislocation.event_extractor import (
    extract_eia_features,
    extract_fomc_features,
    feature_hash,
    score_text,
)


AXES = {
    "axes": {
        "inflation_pressure": {
            "positive": {"inflation remains elevated": 3.0, "elevated": 1.0},
            "negative": {"inflation has eased": 2.0},
        },
        "policy_tightness": {
            "positive": {"raise the target range": 2.5},
            "negative": {"reduce the target range": 2.5},
        },
    }
}


class EventExtractorTests(unittest.TestCase):
    def test_long_phrase_masks_nested_term(self) -> None:
        scores = score_text("Inflation remains elevated.", AXES["axes"])
        self.assertEqual(scores["inflation_pressure"], 3.0)

    def test_signs_are_fixed(self) -> None:
        hawkish = score_text("We will raise the target range.", AXES["axes"])
        dovish = score_text("We will reduce the target range.", AXES["axes"])
        self.assertGreater(hawkish["policy_tightness"], 0)
        self.assertLess(dovish["policy_tightness"], 0)

    def test_fomc_delta_uses_previous_document(self) -> None:
        records = [
            {
                "document_id": "a",
                "source_event_id": "fed:1",
                "document_type": "fomc_statement",
                "published_at": "2024-01-01T14:00:00-05:00",
                "version": 1,
            },
            {
                "document_id": "b",
                "source_event_id": "fed:2",
                "document_type": "fomc_statement",
                "published_at": "2024-02-01T14:00:00-05:00",
                "version": 1,
            },
        ]
        content = {"a": b"Inflation remains elevated.", "b": b"Inflation has eased."}
        features = extract_fomc_features(records, lambda row: content[row["document_id"]], AXES)
        self.assertEqual(features[0]["axis_inflation_pressure"], 0.0)
        self.assertEqual(features[1]["axis_inflation_pressure"], -5.0)
        self.assertEqual(features[1]["previous_document_id"], "a")
        self.assertIn("Inflation has eased", features[1]["added_text"])

    def test_eia_structural_extraction(self) -> None:
        records = [
            {
                "document_id": "e",
                "source_event_id": "eia:1",
                "document_type": "wpsr_table1_csv",
                "published_at": "2024-01-03T10:30:00-05:00",
                "version": 1,
            }
        ]
        content = b"""STUB_1,12/29/23,12/22/23,Difference
Commercial (Excluding SPR),431,436,-5
Strategic Petroleum Reserve (SPR),354,353,1
Total Motor Gasoline,237,226,11
Distillate Fuel Oil,125,115,10
STUB_1,STUB_2,x,x
"""
        features = extract_eia_features(records, lambda _: content)
        self.assertEqual(features[0]["commercial_crude_inventory_change_mmbbl"], -5.0)
        self.assertEqual(features[0]["gasoline_inventory_change_mmbbl"], 11.0)

    def test_feature_hash_is_deterministic(self) -> None:
        fomc = [{"a": 1, "b": "x"}]
        eia = [{"c": -2.0}]
        self.assertEqual(feature_hash(fomc, eia), feature_hash(fomc, eia))


if __name__ == "__main__":
    unittest.main()
