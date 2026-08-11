from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro_dislocation.pit_events import RIGHTS, audit_components
from macro_dislocation.vendor_capture import (
    VendorCaptureStore,
    capture_authenticated_snapshot,
    capture_observation_id,
    capture_stream_jsonl,
    public_endpoint,
    validate_rights_attestation,
)


FIXTURES = Path(__file__).parent / "fixtures"


def full_rights() -> dict[str, bool]:
    return {name: True for name in RIGHTS}


def capture_args(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "provider": "trading_economics",
        "transport": "https_snapshot",
        "endpoint": "https://api.tradingeconomics.com/calendar?c=top-secret",
        "request_started_at": "2030-01-10T13:28:59+00:00",
        "received_at": "2030-01-10T13:29:00+00:00",
        "received_monotonic_ns": 1_000_000_000,
        "http_status": 200,
        "license_class": "licensed_test_fixture",
        "rights_profile": full_rights(),
        "provenance": "unit_test_fixture",
    }
    values.update(changes)
    return values


def valid_attestation() -> dict[str, object]:
    return {
        "approved": True,
        "agreement_id": "agreement-2026-001",
        "approved_by": "data-governance",
        "attested_at": "2026-08-10T00:00:00+00:00",
        "provider": "Trading Economics",
        "license_class": "licensed_internal_research",
        "rights": full_rights(),
    }


class VendorCaptureTests(unittest.TestCase):
    def test_public_endpoint_strips_query_fragment_and_userinfo(self) -> None:
        sanitized = public_endpoint(
            "https://user:password@api.example.test/calendar?c=secret#fragment"
        )
        self.assertEqual(sanitized, "https://api.example.test/calendar")

    def test_duplicate_receipts_share_blob_but_append_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            payload = (FIXTURES / "te_calendar_pre_release.json").read_bytes()
            first = store.capture(payload, **capture_args())
            second = store.capture(
                payload,
                **capture_args(
                    request_started_at="2030-01-10T13:29:29+00:00",
                    received_at="2030-01-10T13:29:30+00:00",
                    received_monotonic_ns=31_000_000_000,
                ),
            )
            self.assertTrue(first.inserted_blob)
            self.assertFalse(second.inserted_blob)
            report = store.integrity_report(forbidden_values=["top-secret"])
            self.assertTrue(report["passed"])
            self.assertEqual(report["observations"], 2)
            self.assertEqual(report["unique_raw_blobs"], 1)
            self.assertEqual(report["credential_persistence_matches"], 0)

    def test_snapshot_and_stream_casing_have_one_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            store.capture(
                (FIXTURES / "te_calendar_pre_release.json").read_bytes(),
                **capture_args(),
            )
            store.capture(
                (FIXTURES / "te_calendar_post_release.json").read_bytes(),
                **capture_args(
                    transport="websocket_calendar",
                    endpoint="wss://stream.tradingeconomics.com/?client=top-secret",
                    request_started_at="2030-01-10T13:30:00+00:00",
                    received_at="2030-01-10T13:30:01+00:00",
                    received_monotonic_ns=62_000_000_000,
                    http_status=None,
                ),
            )
            snapshots = store.replay()
            self.assertEqual({item.provider_event_id for item in snapshots}, {"SYNTH-CPI-2030-01"})
            self.assertEqual({item.component for item in snapshots}, {"synthetic_cpi_mom"})
            audit = audit_components(snapshots)[0]
            self.assertTrue(audit["eligible_for_price_join"])
            self.assertAlmostEqual(audit["surprise"], 0.1)

    def test_provider_update_does_not_replace_receive_clock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            result = store.capture(
                (FIXTURES / "te_calendar_post_release.json").read_bytes(),
                **capture_args(
                    transport="websocket_calendar",
                    request_started_at="2030-01-10T13:30:00+00:00",
                    received_at="2030-01-10T13:30:01+00:00",
                ),
            )
            snapshot = result.snapshots[0]
            self.assertEqual(snapshot.snapshot_at, "2030-01-10T13:30:01+00:00")
            self.assertEqual(snapshot.received_at, snapshot.snapshot_at)
            self.assertEqual(snapshot.provider_updated_at, "2030-01-10T13:30:00+00:00")

    def test_replay_index_preserves_capture_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            result = store.capture(
                (FIXTURES / "te_calendar_pre_release.json").read_bytes(),
                **capture_args(),
            )
            replayed = store.replay_index()
            self.assertEqual(set(replayed), {result.observation["capture_id"]})
            self.assertEqual(len(replayed[result.observation["capture_id"]]), 1)

    def test_capture_observation_hash_tamper_fails_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            result = store.capture(
                (FIXTURES / "te_calendar_pre_release.json").read_bytes(),
                **capture_args(),
            )
            self.assertEqual(
                capture_observation_id(result.observation),
                result.observation["capture_id"],
            )
            tampered = dict(result.observation)
            tampered["received_monotonic_ns"] += 1
            store.observations_path.write_text(
                json.dumps(tampered) + "\n", encoding="utf-8"
            )
            report = store.integrity_report()
            self.assertFalse(report["passed"])
            self.assertIn("capture observation hash mismatch", report["violations"][0])

    def test_malformed_json_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            with self.assertRaises(ValueError):
                store.capture(b"{bad-json", **capture_args())
            self.assertEqual(store.observations(), [])
            self.assertEqual(list(store.raw_root.rglob("*.json")), [])

    def test_missing_provider_id_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            payload = json.dumps(
                {"Date": "2030-01-10T13:30:00Z", "Event": "Synthetic CPI"}
            ).encode("utf-8")
            with self.assertRaises(ValueError):
                store.capture(payload, **capture_args())
            self.assertEqual(store.observations(), [])

    def test_corrupt_blob_fails_integrity_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            result = store.capture(
                (FIXTURES / "te_calendar_pre_release.json").read_bytes(),
                **capture_args(),
            )
            store._blob_path(result.observation["payload_sha256"]).write_bytes(b"corrupt")
            self.assertFalse(store.integrity_report()["passed"])
            with self.assertRaises(ValueError):
                store.replay()

    def test_torn_observation_line_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VendorCaptureStore(Path(directory))
            store.observations_path.parent.mkdir(parents=True, exist_ok=True)
            store.observations_path.write_text('{"capture_id":"broken"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                store.observations()

    def test_complete_rights_attestation_is_accepted(self) -> None:
        license_class, rights = validate_rights_attestation(valid_attestation())
        self.assertEqual(license_class, "licensed_internal_research")
        self.assertTrue(all(rights.values()))

    def test_incomplete_rights_attestation_is_rejected(self) -> None:
        value = valid_attestation()
        value["rights"] = {"retention": True}
        with self.assertRaises(ValueError):
            validate_rights_attestation(value)

    def test_wrong_provider_rights_attestation_is_rejected(self) -> None:
        value = valid_attestation()
        value["provider"] = "Unrelated Vendor"
        with self.assertRaises(ValueError):
            validate_rights_attestation(value)

    def test_authenticated_capture_requires_environment_credential(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attestation = root / "rights.json"
            attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "TRADING_ECONOMICS_API_KEY"):
                    capture_authenticated_snapshot(
                        VendorCaptureStore(root / "store"),
                        rights_attestation_path=attestation,
                        country="united states",
                        indicators=["cpi"],
                        start="2026-01-01",
                        end="2026-01-02",
                    )

    def test_reflected_credential_is_rejected_before_snapshot_persistence(self) -> None:
        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"echo":"vendor-secret"}'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attestation = root / "rights.json"
            attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
            store = VendorCaptureStore(root / "store")
            with patch.dict(
                os.environ, {"TRADING_ECONOMICS_API_KEY": "vendor-secret"}, clear=True
            ), patch("macro_dislocation.vendor_capture.urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "reflected"):
                    capture_authenticated_snapshot(
                        store,
                        rights_attestation_path=attestation,
                        country="united states",
                        indicators=["cpi"],
                        start="2026-01-01",
                        end="2026-01-02",
                    )
            self.assertEqual(store.observations(), [])

    def test_reflected_credential_is_rejected_before_stream_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attestation = root / "rights.json"
            attestation.write_text(json.dumps(valid_attestation()), encoding="utf-8")
            store = VendorCaptureStore(root / "store")
            lines = ['{"topic":"calendar","echo":"vendor-secret"}\n']
            with patch.dict(
                os.environ, {"TRADING_ECONOMICS_API_KEY": "vendor-secret"}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "reflected"):
                    capture_stream_jsonl(
                        store, lines, rights_attestation_path=attestation
                    )
            self.assertEqual(store.observations(), [])


if __name__ == "__main__":
    unittest.main()
