# Phase 1 protocol: point-in-time release ingestion

Phase 1 does not rescue or retune the Phase 0 price model. The registered Phase 0
result remains No-Go. This phase tests a new, narrower proposition: can official
release material be acquired, versioned and transformed into a few reproducible
event fields without leaking later revisions into an earlier vintage?

The machine-learning boundary is deliberate. A future frozen language model may
map documents to the same small event schema, but Phase 1 fits no neural network
and predicts no price. The registered extractor is a zero-fit lexical-difference
baseline with six axes. Its output is a candidate model input and must not be
described as causal contribution, sentiment truth or a trade signal.

## Frozen acquisition set

- Federal Reserve: every page titled exactly “Federal Reserve issues FOMC
  statement” in the official 2022, 2023 and 2024 FOMC press-release indexes.
- EIA: every 2024 WPSR archive issue listed by the official archive index, using
  the issue-specific `table1.csv`, not the mutable current-week URL.

The expected floor is 24 Fed statements and 50 EIA weekly files. BLS and OPEC are
catalogued but not in the completion gate because their sites returned HTTP 403 to
this environment. Commercial calendar/news sources are not counted without a
contract and retention rights.

## Immutable vintage model

Raw response bytes are stored by SHA-256. The SQLite manifest has one document row
per `(source, source_event_id, content_sha256)` and a separate row for every fetch
observation. Identical re-fetches therefore prove availability without inventing a
new version. Changed bytes under the same source event ID create version 2, 3, and
so on; earlier blobs are never overwritten.

`scheduled_at`, `published_at`, `first_seen_at`, `received_at` and
`feature_ready_at` are distinct. Historical archive retrieval can recover an
official or schedule-inferred publication time but cannot recover when a live
system would actually have received the item. `timestamp_basis` records this
limitation. Archive retrieval timestamps must never be used as historical latency.

## Fixed event axes

The six FOMC wording-difference axes are frozen in `config/event_axes.json`:

1. inflation pressure;
2. labor strength;
3. growth strength;
4. policy tightness;
5. uncertainty;
6. conditionality.

Each statement is compared only with the immediately preceding statement in
publication order. Phrase and unigram weights are fixed in advance; there is no
fit. Added language contributes its signed lexicon weight and removed language
subtracts it. The report retains added/removed snippets for human audit.

EIA values are parsed structurally rather than passed through the text extractor.
Phase 1 emits current-week changes in commercial crude, gasoline, distillate and
SPR inventories as observed components. Consensus surprises require a licensed
point-in-time calendar and remain unavailable.

## Completion and decision

The machine-readable gates are in `config/phase1_trial_001.json`. The pipeline
passes only if both source families and minimum counts are present, every raw hash
validates, a duplicate fetch produces no new document version, a clean replay has
an identical feature hash, there are at most six text dimensions, at least 18 tests
pass, and no price prediction is run.

Passing means `PASS_PIPELINE_ONLY`: proceed only to a separately preregistered,
limited vendor/feature study. It does not overturn Phase 0, prove an edge or
authorize live trading.
