# Phase 4 protocol: licensed shadow-campaign operations

Phase 4 validates the operational evidence around a release window. It does not
collect licensed data in the absence of credentials, join prices or fit a model.
Phase 3 already proved that payloads can be stored and replayed safely; this phase
tests whether a future live capture can be distinguished from an incomplete or
mis-timed run.

## Registered claim

One deterministic supervisor should be able to build a UTC release-window plan,
verify fresh schedule evidence, require independent clock samples, prove a
pre-release consensus capture, detect stream gaps and reconnects, require every
simultaneous component, and close only after a passing raw-store audit.

The offline drill uses original synthetic schedule and trace fixtures. No vendor
documentation payload or historical archive row is counted as an observation.

## Schedule evidence

The BLS calendar states times in Eastern Time and is updated as needed. Production
runs must therefore preserve the exact schedule bytes, source URL, local capture
time and SHA-256 used to make each plan. Named timezone conversion is required so
daylight-saving changes are not represented by a hard-coded UTC offset.

The relevant official references are:

- <https://www.bls.gov/schedule/2026/home.htm>;
- <https://www.bls.gov/schedule/news_release/empsit.htm>;
- <https://docs.tradingeconomics.com/economic_calendar/streaming/>.

If the trace schedule hash differs from the plan, the run fails. The remedy is a
new immutable plan, not editing the previous schedule in place.

## Release-window state

The registered synthetic window starts the stream two minutes before release,
targets the consensus snapshot one minute before release and keeps the stream open
for two minutes after release. These short fixture values test the state machine;
production lead and tail settings require a later operational decision.

At least three clock samples must have median absolute offset no greater than 50
milliseconds and RTT no greater than 200 milliseconds. Heartbeat telemetry gaps
may not exceed 35 seconds. An explicit reconnect gap may not exceed 20 seconds.
Both expected synthetic CPI components must arrive within five seconds after the
scheduled time.

## Failure injection

The frozen invalid traces are unsafe clock, missing pre-release snapshot,
telemetry gap, schedule-hash drift, missing simultaneous component and raw-store
integrity failure. Each must produce its registered issue code and an incomplete
window.

## Campaign promotion

The offline drill can produce only `READY_TO_START_LICENSED_SHADOW_CAMPAIGN`.
Promotion requires at least six fully complete licensed empirical windows,
including three CPI and three NFP windows. Synthetic drills always contribute
zero. Operational promotion still does not prove predictive edge or authorize
trading.

The machine-readable policy is frozen in `config/phase4_trial_001.json`; evidence
and promotion semantics are frozen in `config/shadow_campaign_contract.json`.
