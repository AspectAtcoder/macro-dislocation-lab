from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from macro_dislocation.pit_events import (
    RIGHTS,
    PitSnapshot,
    audit_components,
    build_calendar_bundles,
    bundle_hash,
    load_official_feature_bundles,
    load_research_calendar,
    normalize_trading_economics_snapshot,
    validate_component,
)


def full_rights() -> dict[str, bool]:
    return {name: True for name in RIGHTS}


def te_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "CalendarId": "123",
        "Date": "2024-01-11T13:30:00",
        "Country": "United States",
        "Category": "Inflation Rate",
        "Event": "CPI MoM",
        "Reference": "Dec",
        "SourceURL": "https://www.bls.gov/cpi/",
        "Actual": "",
        "Previous": "0.1%",
        "Forecast": "0.2%",
        "Revised": "",
        "Unit": "%",
        "LastUpdate": "2024-01-10T12:00:00",
    }
    row.update(changes)
    return row


def normalized(row: dict[str, object], snapshot_at: str) -> PitSnapshot:
    return normalize_trading_economics_snapshot(
        [row],
        snapshot_at=snapshot_at,
        received_at=snapshot_at,
        rights_profile=full_rights(),
        license_class="licensed_test_fixture",
    )[0]


class PitEventTests(unittest.TestCase):
    def test_research_calendar_flattens_without_inventing_vintage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            path.write_text(
                "event_id,event_type,release_timestamp_utc,reference_period,"
                "cpi_mom_actual_pct,cpi_mom_forecast_pct,cpi_mom_previous_pct,"
                "core_cpi_mom_actual_pct,core_cpi_mom_forecast_pct,"
                "core_cpi_mom_previous_pct,consensus_source_url,quality_flags\n"
                "2024-01-11_cpi,CPI,2024-01-11T13:30:00+00:00,2023-12,"
                "0.3,0.2,0.1,0.3,0.3,0.3,https://example.test,research\n",
                encoding="utf-8",
            )
            snapshots = load_research_calendar(path)
            self.assertEqual(len(snapshots), 2)
            self.assertTrue(all(item.snapshot_at is None for item in snapshots))
            self.assertTrue(all(not any(item.rights_profile.values()) for item in snapshots))

    def test_research_final_row_fails_closed(self) -> None:
        snapshot = PitSnapshot(
            provider="research_calendar",
            provider_event_id="event:cpi",
            event_type="CPI",
            component="cpi_mom",
            country="United States",
            currency="USD",
            scheduled_at="2024-01-11T13:30:00+00:00",
            reference_period="2023-12",
            unit="percent",
            snapshot_at=None,
            received_at=None,
            actual=0.3,
            consensus=0.2,
            previous=0.1,
            revised=None,
            source_url="https://example.test",
            license_class="research_only_unknown_rights",
            rights_profile={name: False for name in RIGHTS},
            payload_sha256="a" * 64,
            provenance="final_cache_no_vintage",
        )
        audit = validate_component([snapshot])
        self.assertFalse(audit["eligible_for_price_join"])
        self.assertIn("missing_pre_release_snapshot_at", audit["issues"])
        self.assertIn("unproven_consensus_vintage", audit["issues"])
        self.assertIn("research_only_or_unknown_rights", audit["issues"])

    def test_valid_pre_and_post_snapshots_are_eligible(self) -> None:
        pre = normalized(te_row(), "2024-01-11T13:29:00+00:00")
        post = normalized(
            te_row(Actual="0.3%", LastUpdate="2024-01-11T13:30:01"),
            "2024-01-11T13:30:02+00:00",
        )
        audit = validate_component([pre, post])
        self.assertTrue(audit["eligible_for_price_join"])
        self.assertAlmostEqual(audit["surprise"], 0.1)
        self.assertEqual(audit["previous_as_published"], 0.1)

    def test_revision_does_not_overwrite_pre_release_previous(self) -> None:
        pre = normalized(te_row(Previous="0.1%"), "2024-01-11T13:29:00+00:00")
        release = normalized(
            te_row(Actual="0.3%", Revised="0.15%"),
            "2024-01-11T13:30:01+00:00",
        )
        later = normalized(
            te_row(Actual="0.3%", Revised="0.2%", LastUpdate="2024-01-12T12:00:00"),
            "2024-01-12T12:00:01+00:00",
        )
        audit = validate_component([pre, release, later])
        self.assertEqual(audit["previous_as_published"], 0.1)
        self.assertEqual(audit["revised_previous_at_release"], 0.15)
        self.assertEqual(audit["latest_revised_previous"], 0.2)
        self.assertEqual(
            [item["revised"] for item in audit["revision_history"]], [0.15, 0.2]
        )
        self.assertEqual(audit["snapshot_count"], 3)

    def test_missing_right_rejects_otherwise_valid_component(self) -> None:
        pre = normalized(te_row(), "2024-01-11T13:29:00+00:00")
        post = normalized(te_row(Actual="0.3%"), "2024-01-11T13:30:01+00:00")
        post = replace(post, rights_profile={**full_rights(), "machine_learning": False})
        audit = validate_component([pre, post])
        self.assertFalse(audit["eligible_for_price_join"])
        self.assertIn("research_only_or_unknown_rights", audit["issues"])

    def test_naive_capture_timestamp_is_rejected_at_import(self) -> None:
        with self.assertRaises(ValueError):
            normalized(te_row(), "2024-01-11T13:29:00")

    def test_simultaneous_components_form_one_bundle(self) -> None:
        base = {
            "provider": "vendor",
            "event_type": "CPI",
            "country": "United States",
            "currency": "USD",
            "scheduled_at": "2024-01-11T13:30:00+00:00",
            "reference_period": "2023-12",
            "snapshot_count": 2,
            "eligible_for_price_join": True,
            "issues": [],
            "consensus": 0.2,
            "actual": 0.3,
            "previous_as_published": 0.1,
            "revised_previous_at_release": None,
            "latest_revised_previous": None,
            "revision_history": [],
            "consensus_snapshot_at": "2024-01-11T13:29:00+00:00",
            "actual_snapshot_at": "2024-01-11T13:30:01+00:00",
            "surprise": 0.1,
        }
        audits = [
            {**base, "provider_event_id": "1", "component": "cpi_mom"},
            {**base, "provider_event_id": "2", "component": "core_cpi_mom"},
        ]
        bundles = build_calendar_bundles(audits)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0]["component_count"], 2)
        self.assertTrue(bundles[0]["eligible_for_price_join"])

    def test_bundle_hash_is_deterministic(self) -> None:
        value = [{"bundle_id": "a", "components": [{"x": 1}]}]
        self.assertEqual(bundle_hash(value), bundle_hash(value))

    def test_official_feature_rows_are_attached_but_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents.json"
            fomc = root / "fomc.csv"
            eia = root / "eia.csv"
            documents.write_text(
                json.dumps(
                    [
                        {
                            "document_id": "d1",
                            "source_event_id": "fed:fomc:1",
                            "source": "federal_reserve",
                            "scheduled_at": "2024-01-31T19:00:00+00:00",
                            "published_at": "2024-01-31T19:00:00+00:00",
                            "feature_ready_at": "2026-08-10T00:00:00+00:00",
                            "timestamp_basis": "official_page_release_time",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            fomc.write_text(
                "document_id,axis_inflation_pressure\nd1,1.5\n", encoding="utf-8"
            )
            eia.write_text("document_id,commercial_crude_inventory_change_mmbbl\n", encoding="utf-8")
            bundles = load_official_feature_bundles(documents, fomc, eia)
            self.assertEqual(len(bundles), 1)
            self.assertFalse(bundles[0]["eligible_for_price_join"])
            self.assertEqual(bundles[0]["features"]["axis_inflation_pressure"], 1.5)


if __name__ == "__main__":
    unittest.main()
