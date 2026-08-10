# Phase 0 protocol

## Decision question

After the non-tradable release jump, does USD/JPY retain a large and stable enough
15–60 minute drift or reversal to justify licensed point-in-time data and a
low-parameter prediction model?

## Frozen scope for the first run

| Dimension | Value |
|---|---|
| Asset | USD/JPY only |
| Events | U.S. CPI and Employment Situation |
| Sample used for plumbing | 2024, 24 event bundles |
| Observation points | pre-release, +1s, +5s, +30s, +1m, +5m, +15m, +60m |
| Final reference | +60m mid |
| Arrival denominator filter | absolute +60m move >= 2bp |
| Cost proxy | observed event-time bid/ask |

The final statistical experiment must use a longer development sample and an
untouched 2–3 year holdout. The 2024 bootstrap run is descriptive only.

## Labels

Let `P0` be the last valid quote strictly before release and `Ph` the first valid
quote at or after horizon `h`.

- cumulative return: `R_h = 10,000 * (mid_h / mid_0 - 1)`
- raw arrival: `R_h / R_60m`
- completion: `max(0, 1 - |R_60m - R_h| / |R_60m|)`
- residual: `10,000 * (mid_60m / mid_h - 1)`
- executable long residual: `(bid_60m - ask_h) / mid_h * 10,000`
- executable short residual: `(bid_h - ask_60m) / mid_h * 10,000`

Raw arrival is retained because overshoot is informative. Completion is reported
alongside it so an overshoot is not mistaken for clean price discovery.

## Gate

1. Data coverage must be at least 90%, with timestamp defects explicitly listed.
2. If median +5m completion is >=95% for both event types, reject any strategy
   framed as capturing the release jump.
3. A residual strategy advances only if +5m→+15m or +60m changes remain meaningful
   after actual bid/ask and a conservative slippage buffer.
4. Before model selection, freeze a holdout, the feature count (maximum five for
   the first price model), target, and allowed number of trials.
5. First predictor is linear/Ridge. Neural networks may extract text into a few
   event axes but do not directly predict price at this sample size.

## Next statistical test if the gate survives

Use the headline surprise as a control, not the alleged edge. A first model can use
at most: event-type indicator, standardized headline surprise, one simultaneous
component surprise, jump sign/magnitude available at the declared execution time,
and one pre-event regime variable. Predict only the additional return from an
explicit executable start time to +15m. Use walk-forward fitting and report all
attempted specifications.

The single Phase 0 pilot trial is frozen in `config/phase0_trial_001.json`: entry
at +60 seconds, exit at +15 minutes, three features, Ridge alpha 1.0, first 12
events for fitting and last 12 for a fixed chronological test. The 2024 aggregate
study was already inspected, so this is a diagnostic pilot rather than a pristine
holdout. Its purpose is to decide whether the current numeric specification has a
trace worth carrying forward, not to establish profitability.
