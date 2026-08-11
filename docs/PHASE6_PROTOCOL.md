# Phase 6 protocol: prospective campaign roster

Phase 6 freezes the first six official release windows that can satisfy the Phase
4 and Phase 5 campaign floors. It schedules capture operations; it does not create
an empirical observation.

## Registered roster

The BLS Consumer Price Index page lists releases on August 12, September 11 and
October 14, 2026 at 08:30 Eastern. The BLS Employment Situation page lists
September 4, October 2 and November 6, 2026 at 08:30 Eastern. These are the first
three upcoming windows of each family at registration time.

- <https://www.bls.gov/schedule/news_release/cpi.htm>;
- <https://www.bls.gov/schedule/news_release/empsit.htm>.

BLS states that its calendar is updated as needed. Each event therefore requires
a fresh official recheck inside 48 hours of release; the broad roster alone cannot
activate a later window.

## Time conversion

Every official time is converted with `America/New_York`. The August through
October releases occur at 12:30 UTC / 21:30 JST. U.S. daylight-saving time ends
before the November 6 Employment Situation release, so that window occurs at
13:30 UTC / 22:30 JST. A fixed Eastern-to-UTC offset must fail.

## Activation boundary

Credential and approved rights should pass at least 24 hours before release. A
rehearsal deadline is two hours before release. At the frozen evaluation time,
only the August 12 CPI window is inside the 48-hour activation interval. Its
schedule is fresh, but the credential and rights attestation are absent, so its
status is `BLOCKED_VENDOR_ACCESS`.

Missing that window produces no empirical row. The next window remains the
September 4 Employment Situation release, subject to a new official schedule
check and the same access gate.

## Failure injection

The frozen invalid cases apply a fixed UTC offset across the November DST change,
duplicate a release, remove the CPI family floor, use an untrusted source, use a
stale schedule for activation and attempt activation after release. Each must
produce its registered issue.

Passing the offline roster yields
`READY_FOR_CAMPAIGN_ACTIVATION_PENDING_VENDOR_ACCESS`. It does not authorize a
vendor request, price join, model fit or order.
