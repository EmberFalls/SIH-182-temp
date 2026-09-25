# Phase 10 — Cross-chain v1

## Delivered behavior

The v2 cross-chain resolver represents a bridge as three distinct facts:

1. source-chain transfer into a reviewed bridge route;
2. an evidence-bearing cross-chain link; and
3. destination-chain bridge release or mint.

CrossChainResolverV2 creates a VERIFIED link only when all of these hold:

- the route points to a registered BRIDGE entity;
- the bridge route is reviewed;
- the source and destination transfers match the registered chain, bridge-address, and optional asset-contract pairs;
- the destination event follows the source event;
- the destination amount does not exceed the source amount; and
- both events carry the same exact bridge message identifier supplied by the bridge adapter.

The resolver never infers a cross-chain continuation from matching amounts, timing, or user addresses. If exact message proof is absent, callers create a BRIDGE_UNRESOLVED terminal with the full attributed amount and its reason.

## API

- POST /v2/bridges/routes registers a reviewed route.
- GET /v2/bridges/routes lists route records.
- POST /v2/cross-chain/links/resolve persists a verified, evidence-bound source/destination link.
- GET /v2/cross-chain/links and GET /v2/cross-chain/links/{id} retrieve link evidence.
- POST /v2/cross-chain/links/{id}/continuations produces a destination FlowSeed.

A normal destination adapter then passes the returned seed to CrossChainResolverV2.trace_destination(...) with the existing FundFlowEngineV2.

## Flow accounting

When a source allocation is continued, the destination tainted amount is:

~~~
source attributed amount × destination bridge amount / source bridge amount
~~~

This records an observable bridge fee or asset-conversion difference without claiming that source and destination token contracts are identical. Downstream tracing retains the cross-chain link ID as the destination seed evidence.

## Fixtures

fixtures/recorded_real/wormhole_avalanche_fuji_to_base_sepolia_message.json records a public Wormhole testnet source transaction. It is marked RECORDED_REAL and deliberately remains NOT_ELIGIBLE for flow continuation because the public tutorial does not expose both event records and their exact common message ID.

tests/test_cross_chain_v2.py is a fully reproducible SYNTHETIC exact-message pair. It tests the complete source-event → verified link → scaled destination seed → destination trace path. It is never presented as real blockchain intelligence.

Before operational use, replace the source-only recorded fixture with adapter-captured source and destination events plus their verified message identifier.