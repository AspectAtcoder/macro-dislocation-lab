# Phase 5 protocol: empirical evidence enrollment

Phase 5 closes the gap between a release-window trace and the immutable vendor
captures it claims to represent. A trace field such as `capture_id` or
`store_audit.passed=true` is not sufficient evidence by itself.

## Registered claim

The gate must resolve every pre-release snapshot and release component to the
Phase 3 content-addressed store, replay its normalized provider event identities,
compare capture and trace receive clocks, and recompute store integrity. Only a
fully cross-linked window with approved rights, production license metadata and
authenticated provenance can be appended to the empirical campaign ledger.

The offline trial uses one original synthetic CPI bundle, two synthetic capture
receipts, two raw blobs, four normalized snapshots and a 20-event trace. It may
pass structural cross-link checks but must enroll zero empirical windows.

## External access gate

The local environment has no Trading Economics credential or approved rights
attestation at registration time. Phase 5 therefore opens no authenticated
connection. Actual enrollment must wait for both inputs and for scheduled CPI/NFP
release windows; no historical reconstruction is relabeled as a live receipt.

Trading Economics calendar streaming and schema documentation are used only as
interface references:

- <https://docs.tradingeconomics.com/economic_calendar/streaming/>;
- <https://docs.tradingeconomics.com/economic_calendar/schema/>.

Official release scheduling remains anchored to BLS calendars and preserved as
exact versioned bytes:

- <https://www.bls.gov/schedule/2026/home.htm>;
- <https://www.bls.gov/schedule/news_release/cpi.htm>;
- <https://www.bls.gov/schedule/news_release/empsit.htm>.

## Failure injection

The frozen cases remove a capture reference, use an unknown capture ID, drift a
trace receive clock, contradict the real store-integrity report, name a component
absent from the payload, spoof licensed trace provenance over synthetic captures,
and append the same package twice. Every case must fail with its registered issue.

## Gate

Passing the offline trial yields `READY_FOR_LICENSED_EVIDENCE_ENROLLMENT`, not an
empirical campaign promotion. Promotion still requires six distinct licensed
windows, including three CPI and three NFP windows. Market-price joining and model
fitting require a later, separately preregistered trial.
