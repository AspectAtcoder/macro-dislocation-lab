# Phase 0 result

Completed: 2026-08-10

Registered specification commit: `ddaf63f`

Result: **NO-GO for the current three-feature numeric specification**

## Requirements and evidence

| Requirement | Result | Evidence |
|---|---|---|
| Historical consensus availability | PASS WITH CAVEAT | Research calendar acquired; paid PIT availability verified through Trading Economics. Production contract not purchased. |
| Tick/second data availability | PASS | 72 Dukascopy BI5 hours decoded to 997,364 USD/JPY bid/ask ticks. |
| Experiment 0 arrival study | PASS | 24/24 CPI and NFP bundles measured at seven post-release horizons. |
| Residual magnitude after the jump | PASS FOR MEASUREMENT | Median absolute +5m→+60m residual was 10.19 bp for CPI and 19.91 bp for NFP. |
| One low-parameter prediction test | COMPLETE, NO TRACE | Fixed three-feature Ridge model, one trial, 12 chronological train and 12 test events. |
| Event-time costs | PASS FOR PROTOTYPE | Observed Dukascopy bid/ask plus a registered 1.0-pip round-trip slippage buffer. Broker fills remain unavailable. |
| Simultaneous release treatment | PASS | CPI and NFP components are each stored as one event bundle. |
| Train/serve feature parity | PASS | One fitted `FeatureTransformer` performs both training and inference transformation; covered by tests. |
| Trial-count record | PASS | `config/phase0_trial_001.json` and `config/trial_registry.csv`; one allowed and one run. |
| News/PIT source decision | PASS | `config/news_sources.json` and `docs/NEWS_SOURCES.md`. |

## Experiment 0

- Coverage: 24 / 24 events.
- Maximum selected horizon-quote lag: 375 ms; maximum pre-release baseline lead:
  340 ms (10-second rejection tolerance, no rejection required).
- Median +5-minute completion toward the +60-minute level: CPI 68.1%, NFP 69.9%.
- Median absolute residual from +5 minutes to +60 minutes: CPI 10.19 bp,
  NFP 19.91 bp.
- Median +1-second spread: CPI 6.80 pips, NFP 6.15 pips.

The release jump is therefore excluded from the execution target. A residual exists
descriptively, but its direction must be predicted after costs.

## Registered model result

The frozen target was the USD/JPY midpoint return from +60 seconds to +15 minutes.
Features were the train-standardized +60-second initial move, headline surprise and
secondary bundled surprise. Ridge alpha was fixed at 1.0 with no search.

| Metric | Test result |
|---|---:|
| Direction accuracy | 6 / 12 (50.0%) |
| 95% Wilson interval | 25.4%–74.6% |
| Exploratory binomial p-value vs 50% | 1.0000 |
| Model MAE | 24.16 bp |
| Zero-forecast MAE | 24.07 bp |
| Train-mean-forecast MAE | 26.15 bp |
| Median net after bid/ask and buffer | -3.00 bp |
| Net win rate | 41.7% |

Three of four registered trace checks failed. The positive forecast/actual
correlation (0.48) is not promoted because the registered sign, zero-MAE and median
net gates failed and the sample is only twelve test events.

## Decision

- Phase 0 itself is **complete**.
- Release-jump trading is **No-Go**.
- The current numeric residual model is **No-Go**.
- No live capital, full historical-data purchase or neural price predictor is
  justified by this result.
- A text-derived or cross-event pooled model is a new hypothesis and must receive a
  new trial ID. It must not repeatedly tune against this 2024 pilot.
- The multi-day to two-week directional strategy was not tested in Phase 0.

The generated result directory includes an input-hash manifest, event metrics,
arrival chart, model predictions and machine-readable summaries. Raw and processed
market data remain outside Git because of size and redistribution constraints.
