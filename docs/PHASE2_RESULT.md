# Phase 2 result

Phase 2 completed on 2026-08-10 with two deliberately separate decisions:

- pipeline: **READY_FOR_LICENSED_VENDOR_INGESTION**;
- price experiment: **NO_GO_PRICE_EXPERIMENT_VENDOR_DATA_REQUIRED**.

The first says that the fail-closed point-in-time contract and event-bundle layer
work. The second says there is still no admissible consensus dataset for a new
price model.

## Empirical data audit

The registered negative control parsed the existing 2024 CPI/NFP file into 60
components and 24 simultaneous-release bundles:

| Data class | Components or bundles | Price eligible |
|---|---:|---:|
| CPI/NFP research components | 60 | 0 |
| CPI/NFP calendar bundles | 24 | 0 |
| FOMC official-feature bundles | 24 | 0 |
| EIA official-feature bundles | 52 | 0 |
| Total bundles | 100 | 0 |

Every research component failed for the preregistered reasons: no captured
pre-release snapshot timestamp, no proven consensus vintage and no confirmed
retention/ML rights. It also lacks a timestamped post-release actual vintage. This
is the expected negative-control result; a parser that admitted any row would have
failed Phase 2.

FOMC and EIA features were attached to the common bundle representation. Their
historical official publication labels remain available, but archive retrieval in
2026 cannot prove historical live receive or feature-ready latency. They therefore
remain non-price-eligible.

## Contract behavior

The implementation requires an append-only pre-release consensus snapshot and a
post-release actual snapshot. It keeps `previous_as_published`,
`revised_previous_at_release`, `latest_revised_previous` and the full revision
history separately. Components sharing country, currency and scheduled time form
one bundle. Missing timestamps, units, source URLs or any required data right fail
closed.

The 100-bundle replay hash was identical on a clean recomputation:

`9604a67c4eed08e1bf1ab42ea1f9fcc239b35e9d62b33b3281ac4dc8d14c6bb1`

All 36 unit tests and every `verify-phase2` check passed. The verifier confirms
that the active specification and PIT contract match preregistration commit
`e2b1b73` and that every input hash is unchanged.

## Vendor preflight

No `TRADING_ECONOMICS_API_KEY` was present. The Trading Economics guest endpoint
returned HTTP 410 and zero empirical vendor rows were acquired. Documentation
examples were used only as schema fixtures, never as observations.

The exact sample, fields, rights and acceptance tests required for a paid trial are
recorded in `config/vendor_trial_requirements.json`. An authenticated download is
the next external dependency. Until it exists, running a price join or retuning a
model would violate the data contract and the registered trial discipline.
