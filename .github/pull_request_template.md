## Change

Describe the hypothesis, data contract, or implementation change.

## Leakage and timing checklist

- [ ] Every feature has an explicit as-of timestamp.
- [ ] No revised value is used before it became available.
- [ ] Simultaneous releases remain a single event bundle.
- [ ] Train and serve call the same feature implementation.
- [ ] Event-time bid/ask and conservative slippage are included.
- [ ] Trial count and holdout access are recorded.

## Verification

List tests and generated artifacts. Do not commit licensed or raw market data.
