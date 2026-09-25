# Data sources

| Source | Purpose | Chains | Access | Trust treatment | Refresh |
| --- | --- | --- | --- | --- | --- |
| TronGrid | Confirmed TRC-20 outgoing transfers | TRON | Configured API key | On-chain transfer evidence; provider response metadata retained | Per trace with bounded cache |
| Etherscan V2-compatible API | Confirmed ERC-20 outgoing transfers | Ethereum, BNB Chain, Polygon PoS | Configured API key | On-chain transfer evidence; provider response metadata retained | Per trace with bounded cache |
| Team-reviewed registry entries | VASP and service assertions | Supported chains | Local review workflow | Review state and source are stored per assertion | Manual review |
| Wormhole public documentation fixture | Cross-chain source-event example | Avalanche Fuji to Base Sepolia | Public documentation | Source-only recorded fixture; explicitly not eligible for continuation | Static fixture |

Provider API keys are read from the local environment and never placed in evidence manifests. Public-chain retrieval establishes an observed transfer, not beneficial ownership. Entity attribution requires a separate sourced registry assertion or documented inference.