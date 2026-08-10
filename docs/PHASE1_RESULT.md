# Phase 1 result

Phase 1 was completed on 2026-08-10 with the decision
**PASS_PIPELINE_ONLY**. This proves the registered acquisition, immutable-vintage
storage and deterministic extraction gates. It does not prove price predictability,
an economic edge or execution viability. The Phase 0 price-model result remains
No-Go.

## Evidence

The pipeline downloaded the preregistered official archive set once and then
completed two further network re-acquisitions:

| Source | Documents | Feature rows | Publication-time basis |
|---|---:|---:|---|
| Federal Reserve FOMC statements, 2022–2024 | 24 | 24 | official page release time |
| EIA WPSR table 1, 2024 | 52 | 52 | archive date plus schedule-inferred time |
| Total | 76 | 76 | mixed; explicitly labelled per record |

The first acquisition created 76 document vintages. Both real network
re-acquisitions created zero additional vintages. Including one intentional
duplicate probe in each run, fetch observations increased to 231. The raw/content
hash audit checked all 76 records. Replaying the extractor produced the same
feature hash after every run:

`b0cb6c5b77d3d68a034d2d7bc0b11f775a617048b01e66a5939389034572d9e3`

All 25 unit tests and every `verify-phase1` check passed. The verifier also checks
that the live specification and six-axis lexicon match the preregistration commit
`f00970a`.

## What was built

- content-addressed raw-response and canonical-content blobs;
- SQLite document and observation manifests;
- immutable versioning by source event ID and canonical content hash;
- distinct scheduled, published, first-seen, received and feature-ready times;
- Fed and EIA official-archive adapters;
- a fixed, zero-fit six-axis FOMC wording-difference extractor with review text;
- direct EIA extraction of commercial crude, SPR, gasoline and distillate changes;
- deterministic replay hashes, source-availability output and a fail-closed verifier.

No neural model was fitted. This is intentional: Phase 1 establishes a low-
parameter representation and data lineage before any new price trial.

## Limits that remain

Historical archive fetch time is not historical live arrival time. For EIA, the
archive date is official but the release time is schedule-inferred and is labelled
accordingly. BLS and OPEC returned HTTP 403 in this environment; no access-control
bypass was attempted. Trading Economics, LSEG and Bloomberg were not contracted,
so point-in-time consensus, vendor arrival times, revisions and retention/ML rights
remain unverified.

The six lexical axes are reproducible but not semantically validated ground truth.
They are candidate inputs only, not causal attributions or trading signals. A next
price experiment requires a new preregistration and licensed point-in-time vendor
trial; it must not reuse the already inspected Phase 0 holdout for tuning.
