# Licensed shadow-campaign runbook

This runbook validates collection operations only. It does not join market prices,
fit a model, generate an order or establish an edge.

## Preconditions

1. Complete the Phase 3 credential and written-rights requirements in
   `docs/VENDOR_CAPTURE_RUNBOOK.md`.
2. Preserve the exact schedule input, source URL, local capture time and SHA-256.
   Re-fetch it before the registered freshness limit because official calendars
   can change.
3. Convert Eastern release times with `America/New_York`. Do not use a fixed UTC
   offset across daylight-saving transitions.
4. Confirm host time synchronization independently. Phase 4 NTP samples are
   unauthenticated diagnostics and do not replace the operating system's NTP
   service.
5. Keep schedules, details files, raw payloads and traces under ignored
   `data/raw/` or `data/private/` paths.

## Build an immutable release plan

Normalize the licensed or official schedule into the schema demonstrated by
`tests/fixtures/shadow_release_schedule.json`, then run:

```bash
macro-lab plan-shadow-window \
  --schedule data/raw/schedules/release_schedule.json \
  --output data/raw/shadow/plans.json
```

Each plan includes the schedule hash, schedule receipt time, expected component
set, stream start, pre-snapshot target and stream end. If the schedule changes,
create a new plan and run ID. Never edit the earlier trace.

## Start the append-only trace

Create one small JSON details file per event. It must not contain credentials. For
`run_started`, include the plan's `schedule_sha256` and
`"provenance": "licensed_shadow"`. Record it with:

```bash
macro-lab record-shadow-event \
  --run-id RUN_ID \
  --plan-id PLAN_ID \
  --kind run_started \
  --details-file data/private/run_started.json \
  --trace-store data/raw/shadow/RUN_ID
```

The command adds local UTC and monotonic receive clocks and appends a hashed event
to `trace.jsonl`.

## Record clock evidence

Before connecting, collect at least three distinct samples:

```bash
macro-lab record-shadow-clock-sample \
  --server NTP_SERVER \
  --run-id RUN_ID \
  --plan-id PLAN_ID \
  --trace-store data/raw/shadow/RUN_ID
```

The audit rejects insufficient sources, non-finite values, median absolute offset
over 50 ms or RTT over 200 ms. Record system clock-sync status separately.

## Capture the release window

Use the Phase 3 recorder for the actual HTTPS snapshot and calendar stream. Add
Phase 4 trace events for:

1. `stream_connected` before `stream_start_at`;
2. `heartbeat` at intervals safely below 35 seconds;
3. `pre_snapshot_captured` with the Phase 3 capture ID and every expected
   consensus component;
4. one `release_component` per expected provider component and its capture ID;
5. explicit `stream_disconnected` and `stream_reconnected` events for every gap;
6. `store_audit` with the Phase 3 integrity result;
7. `stream_closed` only after `stream_end_at`.

Every event is appended with `record-shadow-event`. A reconnect is evidence, not a
reason to overwrite the original connection history.

## Audit

```bash
macro-lab audit-shadow-run \
  --schedule data/raw/schedules/release_schedule.json \
  --trace-store data/raw/shadow/RUN_ID \
  --plan-id PLAN_ID \
  --output data/raw/shadow/RUN_ID/audit.json
```

Only hash-valid, operationally complete traces with licensed provenance can count.
The campaign needs six distinct release plans and release times: at least three CPI
and three NFP. Synthetic or repeated runs count as zero. Meeting that operational
gate still requires a new preregistration before any market-price join.
