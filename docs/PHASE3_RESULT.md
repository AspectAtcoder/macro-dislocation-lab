# Phase 3 result

Phase 3 completed on 2026-08-10 with two separate decisions:

- capture pipeline: **READY_FOR_AUTHENTICATED_SHADOW_CAPTURE**;
- price experiment: **NO_GO_PRICE_EXPERIMENT_SHADOW_DATA_REQUIRED**.

The capture decision means that the offline integrity and security gates passed.
It does not mean that licensed empirical data exists or that a price model may be
run.

## Registered offline replay

The frozen plan recorded the pre-release HTTPS fixture twice and the post-release
calendar-stream fixture once:

| Item | Count |
|---|---:|
| Capture observations | 3 |
| Unique immutable raw payloads | 2 |
| Normalized snapshots | 3 |
| Audited components | 1 |
| Event bundles | 1 |
| Structurally eligible synthetic components | 1 |
| Empirical vendor rows | 0 |

The duplicate payload generated a second observation without overwriting or
duplicating the content-addressed blob. HTTPS title-case fields and stream
lower-case fields resolved to the same stable provider ID and component.

## Time and revision semantics

The store keeps request start, local UTC receipt, local monotonic receipt and the
provider's `LastUpdate` separately. The normalized `snapshot_at` is the local
receipt time; provider time is not used to manufacture an earlier capture.

The pre-release consensus and post-release actual formed one structurally valid
synthetic component. The previous-as-published and revised value remained
separate. Because its provenance is synthetic, this result contributes zero
empirical price-eligible rows.

## Integrity and security

The deterministic replay hash was:

`057162dca6b236cc684b2d51390b5a743d1b1634dc5553f4e1e677208efc3c51`

No synthetic credential marker was present in the store. Malformed JSON, missing
provider identity, incomplete rights, a credential-bearing endpoint and a
corrupted blob all failed closed. Reflected credentials in HTTPS bodies and stream
messages are also rejected before persistence.

All 53 unit tests and every `verify-phase3` check passed. The verifier confirms
that the active specification, capture contract and PIT contract match
preregistration commit `8801e55` and that all registered input hashes are
unchanged.

## Remaining external gate

No authenticated vendor request or WebSocket connection was made. Production
shadow capture requires a user-supplied `TRADING_ECONOMICS_API_KEY` and a written
rights attestation that passes
`config/vendor_rights_attestation.schema.json`. Until several real CPI/NFP release
cycles have been captured and audited, market joining and model fitting remain
prohibited.
