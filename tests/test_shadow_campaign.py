from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro_dislocation.shadow_campaign import (
    NTP_EPOCH_DELTA,
    ShadowTraceStore,
    audit_shadow_trace,
    build_release_plans,
    campaign_promotion_gate,
    create_trace_event,
    load_trace_fixture,
    official_local_to_utc,
    query_ntp_clock_sample,
    shadow_audit_hash,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIFICATION = json.loads(
    (PROJECT_ROOT / "config/phase4_trial_001.json").read_text(encoding="utf-8")
)
POLICY = SPECIFICATION["policy"]
SCHEDULE = PROJECT_ROOT / "tests/fixtures/shadow_release_schedule.json"
TRACE = PROJECT_ROOT / "tests/fixtures/shadow_trace_pass.json"


def plan_and_trace() -> tuple[object, list[dict[str, object]]]:
    plan = build_release_plans(SCHEDULE, POLICY)[0]
    return plan, load_trace_fixture(TRACE, plan)


class ShadowCampaignTests(unittest.TestCase):
    def test_named_zone_conversion_handles_dst(self) -> None:
        self.assertEqual(
            official_local_to_utc("2030-01-10", "08:30:00"),
            "2030-01-10T13:30:00+00:00",
        )
        self.assertEqual(
            official_local_to_utc("2030-07-10", "08:30:00"),
            "2030-07-10T12:30:00+00:00",
        )

    def test_release_plan_is_deterministic_and_has_registered_window(self) -> None:
        first = build_release_plans(SCHEDULE, POLICY)[0]
        second = build_release_plans(SCHEDULE, POLICY)[0]
        self.assertEqual(first, second)
        self.assertEqual(first.stream_start_at, "2030-01-10T13:28:00+00:00")
        self.assertEqual(first.pre_snapshot_due_at, "2030-01-10T13:29:00+00:00")
        self.assertEqual(first.stream_end_at, "2030-01-10T13:32:00+00:00")

    def test_schedule_requires_https_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = json.loads(SCHEDULE.read_text(encoding="utf-8"))
            value["schedule_source_url"] = "http://unsafe.example.test"
            path = Path(directory) / "schedule.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "https"):
                build_release_plans(path, POLICY)

    def test_stale_schedule_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value = json.loads(SCHEDULE.read_text(encoding="utf-8"))
            value["captured_at"] = "2029-12-01T00:00:00+00:00"
            path = Path(directory) / "schedule.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "older"):
                build_release_plans(path, POLICY)

    def test_append_only_trace_round_trip(self) -> None:
        plan, trace = plan_and_trace()
        with tempfile.TemporaryDirectory() as directory:
            store = ShadowTraceStore(Path(directory))
            for event in trace:
                store.append(event)
            self.assertEqual(store.events(), trace)
            audit = audit_shadow_trace(plan, store.events(), POLICY)
            self.assertTrue(audit["operationally_complete"])

    def test_live_trace_event_uses_current_dual_clocks(self) -> None:
        with patch(
            "macro_dislocation.shadow_campaign.time.monotonic_ns", return_value=123456
        ):
            event = create_trace_event(
                run_id="run",
                plan_id="plan",
                kind="heartbeat",
                details={"connection_id": "connection"},
            )
        self.assertEqual(event["received_monotonic_ns"], 123456)
        self.assertTrue(event["observed_at"].endswith("+00:00"))
        self.assertEqual(len(event["event_id"]), 64)

    def test_torn_trace_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ShadowTraceStore(Path(directory))
            store.path.write_text('{"event_id":"broken"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "torn"):
                store.events()

    def test_trace_event_hash_tamper_fails_closed(self) -> None:
        _, trace = plan_and_trace()
        with tempfile.TemporaryDirectory() as directory:
            store = ShadowTraceStore(Path(directory))
            stored = store.append(trace[0])
            stored["event_id"] = "0" * 64
            store.path.write_text(json.dumps(stored) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                store.events()

    def test_valid_trace_is_complete_but_not_empirical(self) -> None:
        plan, trace = plan_and_trace()
        audit = audit_shadow_trace(plan, trace, POLICY)
        self.assertTrue(audit["operationally_complete"])
        self.assertFalse(audit["empirical_window"])
        self.assertEqual(audit["metrics"]["reconnect_gaps_seconds"], [8.0])
        self.assertEqual(audit["issues"], [])

    def test_each_registered_failure_is_detected(self) -> None:
        plan, trace = plan_and_trace()
        cases: list[tuple[str, list[dict[str, object]]]] = []

        unsafe = json.loads(json.dumps(trace))
        for event in unsafe:
            if event["kind"] == "clock_sample":
                event["details"]["offset_ms"] = 500.0
        cases.append(("clock_offset_exceeded", unsafe))

        cases.append(
            (
                "missing_pre_release_snapshot",
                [event for event in trace if event["kind"] != "pre_snapshot_captured"],
            )
        )
        cases.append(
            (
                "missing_release_component",
                [
                    event
                    for event in trace
                    if not (
                        event["kind"] == "release_component"
                        and event["details"].get("component_id") == "SYNTH-CPI-CORE"
                    )
                ],
            )
        )
        for expected, value in cases:
            audit = audit_shadow_trace(plan, value, POLICY)
            self.assertIn(expected, audit["issues"])
            self.assertFalse(audit["operationally_complete"])

    def test_nonfinite_clock_and_reused_server_fail_closed(self) -> None:
        plan, trace = plan_and_trace()
        value = json.loads(json.dumps(trace))
        for event in value:
            if event["kind"] == "clock_sample":
                event["details"]["server"] = "same-server.invalid"
                event["details"]["offset_ms"] = float("nan")
        audit = audit_shadow_trace(plan, value, POLICY)
        self.assertIn("clock_offset_exceeded", audit["issues"])
        self.assertIn("insufficient_independent_clock_sources", audit["issues"])
        self.assertFalse(audit["operationally_complete"])

    def test_synthetic_audit_never_promotes_campaign(self) -> None:
        plan, trace = plan_and_trace()
        audit = audit_shadow_trace(plan, trace, POLICY)
        result = campaign_promotion_gate([audit], POLICY)
        self.assertFalse(result["promoted"])
        self.assertEqual(result["complete_empirical_windows"], 0)

    def test_three_cpi_and_three_nfp_empirical_windows_promote(self) -> None:
        plan, trace = plan_and_trace()
        base = audit_shadow_trace(plan, trace, POLICY)
        audits = []
        for index in range(6):
            item = json.loads(json.dumps(base))
            item["run_id"] = f"licensed-{index}"
            item["plan_id"] = f"licensed-plan-{index}"
            item["empirical_window"] = True
            item["provenance"] = "licensed_shadow"
            item["event_family"] = "CPI" if index < 3 else "NFP"
            item["scheduled_at"] = f"2030-0{index + 1}-10T13:30:00+00:00"
            item["audit_hash"] = shadow_audit_hash(item)
            audits.append(item)
        result = campaign_promotion_gate(audits, POLICY)
        self.assertTrue(result["promoted"])
        self.assertEqual(result["complete_cpi_windows"], 3)
        self.assertEqual(result["complete_nfp_windows"], 3)

    def test_duplicate_run_id_blocks_promotion(self) -> None:
        plan, trace = plan_and_trace()
        base = audit_shadow_trace(plan, trace, POLICY)
        base["empirical_window"] = True
        base["provenance"] = "licensed_shadow"
        audits = []
        for index in range(6):
            item = json.loads(json.dumps(base))
            item["run_id"] = f"run-{index}"
            item["plan_id"] = f"plan-{index}"
            item["event_family"] = "CPI" if index < 3 else "NFP"
            item["scheduled_at"] = f"2030-0{index + 1}-10T13:30:00+00:00"
            item["audit_hash"] = shadow_audit_hash(item)
            audits.append(item)
        audits.append(json.loads(json.dumps(audits[0])))
        result = campaign_promotion_gate(audits, POLICY)
        self.assertFalse(result["promoted"])
        self.assertIn("duplicate_run_id", result["reasons"])

    def test_duplicate_plan_id_blocks_promotion(self) -> None:
        plan, trace = plan_and_trace()
        base = audit_shadow_trace(plan, trace, POLICY)
        audits = []
        for index in range(6):
            item = json.loads(json.dumps(base))
            item["run_id"] = f"run-{index}"
            item["plan_id"] = "same-plan" if index < 2 else f"plan-{index}"
            item["empirical_window"] = True
            item["provenance"] = "licensed_shadow"
            item["event_family"] = "CPI" if index < 3 else "NFP"
            item["scheduled_at"] = f"2030-0{index + 1}-10T13:30:00+00:00"
            item["audit_hash"] = shadow_audit_hash(item)
            audits.append(item)
        result = campaign_promotion_gate(audits, POLICY)
        self.assertFalse(result["promoted"])
        self.assertIn("duplicate_plan_id", result["reasons"])

    def test_modified_audit_hash_blocks_promotion(self) -> None:
        plan, trace = plan_and_trace()
        audit = audit_shadow_trace(plan, trace, POLICY)
        audit["empirical_window"] = True
        audit["provenance"] = "licensed_shadow"
        result = campaign_promotion_gate([audit], POLICY)
        self.assertFalse(result["promoted"])
        self.assertIn("invalid_empirical_audit", result["reasons"])

    def test_ntp_sample_computes_offset_and_rtt(self) -> None:
        class FakeSocket:
            def __init__(self) -> None:
                self.request = b""

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def settimeout(self, timeout: float) -> None:
                self.timeout = timeout

            def sendto(self, request: bytes, target: tuple[str, int]) -> None:
                self.request = bytes(request)

            @staticmethod
            def _stamp(value: float) -> bytes:
                ntp = value + NTP_EPOCH_DELTA
                seconds = int(ntp)
                fraction = int((ntp - seconds) * 2**32)
                return struct.pack("!II", seconds, fraction)

            def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
                response = bytearray(48)
                response[0] = 0x24
                response[1] = 2
                response[24:32] = self.request[40:48]
                response[32:40] = self._stamp(1_000.005)
                response[40:48] = self._stamp(1_000.006)
                return bytes(response), ("192.0.2.1", 123)

        fake = FakeSocket()
        with patch("macro_dislocation.shadow_campaign.socket.socket", return_value=fake), patch(
            "macro_dislocation.shadow_campaign.time.time", side_effect=[1_000.0, 1_000.02]
        ), patch(
            "macro_dislocation.shadow_campaign.time.monotonic_ns",
            side_effect=[100, 20_000_100],
        ):
            event = query_ntp_clock_sample(
                "ntp.example.test", run_id="run", plan_id="plan"
            )
        self.assertAlmostEqual(event["details"]["offset_ms"], -4.5, places=3)
        self.assertAlmostEqual(event["details"]["rtt_ms"], 19.0, places=3)

    def test_ntp_server_name_rejects_whitespace(self) -> None:
        with self.assertRaises(ValueError):
            query_ntp_clock_sample("bad server", run_id="run", plan_id="plan")


if __name__ == "__main__":
    unittest.main()
