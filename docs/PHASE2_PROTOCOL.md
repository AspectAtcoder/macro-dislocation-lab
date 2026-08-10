# Phase 2 protocol: point-in-time calendar contract and event bundles

Phase 2 is a data-admissibility test, not a second attempt at the failed Phase 0
price model. Its job is to prove that the repository can distinguish information
known before a release from values learned after it, preserve revisions, merge
simultaneous components and attach Phase 1 official-document features without
silently making archive timestamps look live.

## Frozen data contract

The normalized unit is an append-only snapshot of one event component. A component
is eligible for a future price experiment only when the store contains both:

1. a snapshot strictly before the scheduled release with a non-null consensus;
2. a snapshot at or after release with a non-null actual.

Provider event identity, component, scheduled time and reference period must remain
stable across snapshots. `previous` and `revised` are separate values. A revision
creates another snapshot and never mutates the pre-release state. All timestamps
must be offset-aware. Retention, backtesting, ML-training and derived-data rights
must each be explicitly true; unknown is failure.

Components with the same country, currency and scheduled timestamp are one bundle.
This prevents CPI, core CPI or employment subcomponents released together from
being treated as independent samples.

## Registered negative control

The existing 2024 CPI/NFP file contains useful final actual, forecast and previous
values, with official BLS release times replacing unreliable calendar times. It
does not contain a captured pre-release snapshot timestamp, an authenticated
vendor arrival timestamp or sufficient data rights. Phase 2 must parse its 24
events and 60 components, but mark all 60 ineligible for a price experiment. If a
single component passes, the contract has failed open.

## Official-feature bundles

Phase 1 supplies 24 FOMC wording rows and 52 EIA component rows. They are attached
as 76 official-feature bundles while preserving their publication and
feature-ready timing labels. Historical archive retrieval does not establish live
delivery latency, so these bundles remain non-price-eligible until a live or
provider-certified point-in-time path supplies that evidence.

## Vendor preflight

Trading Economics documents a Point-in-Time Economic Calendar endpoint with
Actual, Forecast, Previous, Revised and LastUpdate fields. An authenticated API key
is still required. Phase 2 records whether the configured credential exists and
the actual HTTP status of the discontinued guest path. Documentation examples are
schema fixtures only and are never counted as empirical observations.

## Completion and decisions

The machine-readable gates are frozen in `config/phase2_trial_001.json`. Passing
means `READY_FOR_LICENSED_VENDOR_INGESTION`: the harness is ready and bad local
data was rejected. It does not authorize a price join or a model run. The economic
decision remains No-Go until licensed point-in-time snapshots and written
retention/backtesting/ML/derived-data rights are supplied.
