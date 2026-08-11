# Phase 4 result

Phase 4 completed on 2026-08-11 with separate pipeline, campaign and economic
decisions:

- pipeline: **READY_TO_START_LICENSED_SHADOW_CAMPAIGN**;
- campaign promotion: **false**;
- price experiment: **NO_GO_PRICE_EXPERIMENT_EMPIRICAL_TRIAL_REQUIRED**.

The pipeline decision means the synthetic operational drill and its registered
failure injections passed. It does not mean a licensed release has been captured.

## Registered release-window drill

The frozen trace contained 20 events around one synthetic CPI release:

| Evidence | Result |
|---|---:|
| Release-window plans | 1 |
| Expected simultaneous components | 2 |
| Trace events | 20 |
| Explicit disconnect/reconnect pairs | 1 |
| Complete empirical windows | 0 |

The trace started the stream before the registered lead time, provided three
independent clock samples, captured a consensus snapshot 55 seconds before the
release, received both components 0.8 and 1.1 seconds after the scheduled time,
reconnected after an eight-second gap, passed raw-store integrity and closed after
the post-release tail.

Median absolute clock offset was 4 ms, maximum clock RTT was 18 ms and maximum
telemetry gap was 30.8 seconds. These are synthetic control values, not measured
vendor latency.

## Integrity and failure injection

The deterministic audit hash was:

`cc89e03c20fb254b719f6920d7e0e98a7e57dcca5725618f38bd52030c789d23`

Unsafe clock, missing pre-release snapshot, excessive telemetry gap, schedule-hash
drift, missing simultaneous component and raw-store failure each produced its
registered issue and an incomplete window.

The promotion gate also rejects duplicate run IDs, duplicate plan IDs, duplicate
release windows, modified audit hashes and non-licensed provenance. Six distinct,
hash-valid licensed windows are required, including three CPI and three NFP.

All 74 unit tests and every `verify-phase4` check passed. The verifier confirms
that the active trial, campaign contract, Phase 3 capture contract and both
fixtures match preregistration commit `f13eb5d`.

## Remaining external gate

The offline drill opened no Trading Economics connection, made no authenticated
request and contacted no NTP server. The next run requires a paid credential,
written rights and real release-window evidence. Operational promotion would still
not authorize price joining, model fitting or trading.
