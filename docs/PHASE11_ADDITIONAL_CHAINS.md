# Phase 11 — Additional chain capability

## Traceable chains

| Chain | Transfer retrieval | Fund allocation | Entity labels | Cross-chain |
| --- | --- | --- | --- | --- |
| Ethereum | Full ERC-20 outgoing retrieval | Full | Registry enabled | Experimental |
| TRON | Full TRC-20 outgoing retrieval | Full | Registry enabled | Not implemented |
| BNB Chain | Full ERC-20 outgoing retrieval | Full | Registry enabled | Experimental |
| Polygon PoS | Full ERC-20 outgoing retrieval | Full | Registry enabled | Experimental |
| Bitcoin | Not implemented | Not implemented | Registry enabled | Not implemented |
| Solana | Not implemented | Not implemented | Registry enabled | Not implemented |

BNB Chain and Polygon use the existing Etherscan V2-compatible EVM adapter with chain IDs 56 and 137. They use the same configured explorer API key boundary as Ethereum.

Bitcoin and Solana have address validation only in the wider case model. They do not have a transfer, accounting, or cross-chain adapter in this build, and no user interface presents them as traceable.

## API

GET /v2/capabilities returns the capability matrix. The dashboard retrieves this endpoint at startup and renders the same information for investigators.

## Verification

The focused Phase 11 tests verify the capability declarations, EVM chain IDs, API response, and health endpoint agreement.