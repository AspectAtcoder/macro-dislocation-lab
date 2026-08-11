# Phase 3 protocol: licensed-vendor capture and replay

Phase 3 is an ingestion-integrity trial, not a price experiment. Phase 2 proved
that the current research calendar must not be joined to prices because its
consensus vintage, arrival time and rights are not proven. This phase builds the
next layer required to collect admissible data prospectively.

## Registered claim

One append-only recorder should accept both Trading Economics HTTPS calendar
snapshots and `calendar` streaming messages, preserve their exact bytes, keep
provider update time separate from local receive time, normalize both field
styles through the same Phase 2 function and replay the same snapshots
deterministically.

This claim is tested only with original synthetic fixtures. Values shown in
vendor documentation are schema references and are never counted as empirical
observations.

## Capture clocks

Every observation stores three different clocks:

1. `request_started_at`: local UTC wall clock immediately before the request or
   stream wait;
2. `received_at`: local UTC wall clock immediately after the complete payload is
   in memory;
3. `received_monotonic_ns`: a monotonic reading paired with receipt for ordering
   and elapsed-time checks.

The provider's `LastUpdate` remains `provider_updated_at`. It may precede the
client receipt and may not replace `received_at`. For live messages,
`snapshot_at = received_at`. A historical download made today cannot manufacture
an earlier local receive time.

## Immutable store

Exact payload bytes are stored once by SHA-256. Every receipt appends a JSONL
observation even if its payload hash already exists. Replays resolve each
observation to its immutable blob, verify size and hash, then call the shared
normalizer. Existing blobs and the observation log may never be overwritten or
truncated.

## Rights and credential gate

Production HTTPS or stream capture requires both:

- `TRADING_ECONOMICS_API_KEY` supplied through the environment;
- a separate approved rights attestation identifying the agreement and setting
  retention, historical backtesting, machine learning and derived data rights
  explicitly true.

Secrets are excluded from persisted endpoints, logs, manifests and exceptions.
Missing or placeholder agreement metadata fails before any network request.

## Offline trial and failure injection

The frozen plan captures one pre-release HTTPS fixture twice and one post-release
stream fixture once. The expected result is three observations, two raw blobs,
three normalized snapshots, one component and one simultaneous-release bundle.
The fixture may pass the structural Phase 2 contract but remains non-empirical and
cannot authorize a price join.

The registered negative paths are malformed JSON, missing provider identity,
incomplete rights, a credential-bearing endpoint and a corrupted blob. All must
fail closed.

## Decision

`READY_FOR_AUTHENTICATED_SHADOW_CAPTURE` means only that an authenticated shadow
collector can be started after credentials and written rights are supplied.
`FAIL_CAPTURE_INTEGRITY` means the recorder or its audit is unsafe. Neither result
changes the current economic No-Go or permits model fitting.

The machine-readable counts and gates are frozen in
`config/phase3_trial_001.json`; the envelope rules are frozen in
`config/vendor_capture_contract.json`.
