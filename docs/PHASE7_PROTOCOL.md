# Phase 7 protocol: activation handoff

Phase 7 bridges the official prospective roster to the existing shadow-campaign
schedule. It does not open a vendor connection. A provider component binding is
the missing join key between Phase 6 logical labels and the stable event IDs that
Phase 4/5 must observe in immutable vendor captures.

## Two separate checks

Structural completeness means that every registered logical component maps once
to a unique provider event ID at the exact release timestamp. Execution
eligibility additionally requires a licensed pre-release capture, an immutable
capture ID, all written rights and a `READY_FOR_ACTIVATION` Phase 6 packet.

The registered fixture uses two original synthetic CPI components. It must compile
to one Phase 4 schedule preview so schema drift is visible, but it must never
produce an executable handoff.

## Failure boundary

The frozen invalid cases remove a logical component, duplicate a provider ID,
change a provider timestamp, assert synthetic provenance, corrupt the capture ID,
make the binding stale and attempt to bypass the Phase 6 activation status. Each
must produce its registered issue.

Passing yields `READY_FOR_LICENSED_HANDOFF_PENDING_VENDOR_ACCESS_AND_BINDING`.
An executable handoff remains reserved for a future prospective run with a fresh
BLS roster, user-supplied credential, approved rights and a licensed immutable
pre-release capture. No price, model or order enters this phase.
