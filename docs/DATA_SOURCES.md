# Data sources and provenance

## Release schedule: U.S. Bureau of Labor Statistics

- Source: <https://www.bls.gov/schedule/2024/>
- Role: authoritative release date and 08:30 Eastern Time.
- Local representation: `config/bls_2024_release_schedule.csv`.
- Time conversion: IANA `America/New_York` via Python `zoneinfo`; DST is not
  hard-coded.

## Actual / forecast / previous: public research dataset

- Dataset: <https://huggingface.co/datasets/Ehsanrs2/Forex_Factory_Calendar>
- Upstream description: Forex Factory calendar cache; dataset page declares MIT.
- Role in this repository: **Phase 0 research bootstrap only**.
- Known defect found during ingestion: event components for the same release date
  can carry inconsistent intraday times (for example 00:00 and 17:00). Therefore
  the timestamp is ignored. Only date, event label, Actual, Forecast, and Previous
  are used, then joined to the BLS schedule.
- Production caveat: the dataset page's license label does not establish that the
  upstream calendar content can be commercially redistributed. Do not commit or
  redistribute the raw file. Replace it with a licensed point-in-time consensus
  feed (for example Bloomberg ECO or LSEG) before production research.
- Vintage caveat: the `Previous` field may reflect a revision shown at release
  time, but the dataset does not provide a complete as-of audit trail. It must not
  be treated as guaranteed point-in-time history.

## USD/JPY bid/ask ticks: Dukascopy public datafeed

- Historical-data landing page: <https://www.dukascopy.com/swiss/english/marketwatch/historical/>
- Files used by the downloader: hourly LZMA-compressed `.bi5` records from
  `https://datafeed.dukascopy.com/datafeed/`.
- Record layout: millisecond offset, integer ask, integer bid, ask volume, bid
  volume (`>3i2f`); USD/JPY price scale 1,000.
- Role: exploratory spot-FX quote proxy. FX has no consolidated tape, so these
  quotes represent one venue/feed and are not universal executable prices.
- Cost caveat: reported Bid/Ask is used, but commission, rejects, last-look,
  latency, and additional slippage are not. A live broker's timestamped quote and
  fill logs are required for production cost validation.

## Intentionally not purchased yet

Databento/CME MDP3, Bloomberg ECO, and LSEG data are plausible production inputs,
but purchase is deferred until Experiment 0 demonstrates a residual worth testing.
This prevents paying for data before the basic Go/No-Go gate is passed.
