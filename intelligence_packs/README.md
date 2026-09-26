# Public intelligence packs

This directory holds source-preserving import packs for the v2 intelligence registry.
Every address assertion must carry its source URL, retrieval time, trust tier, and
review state. Imports do **not** become operational VASP labels automatically.

## OFAC public-risk pack

Run:

```powershell
E:\Python\python.exe scripts\build_ofac_crypto_pack.py
```

The script downloads OFAC's public SDN Advanced export, extracts recognizable
Ethereum, TRON, Bitcoin, and Solana digital-currency addresses, and writes
`ofac_crypto_review_queue.csv`. Each row is a `SERVICE` assertion tagged
`OFAC_SANCTIONS|PUBLIC_SOURCE`, with `UNREVIEWED` status. Import it through the
dashboard, inspect every record, and apply local review rules before relying on it.

The pack is deliberately **not** a VASP ownership database. Exchange hot-wallet,
deposit-wallet, mixer, and bridge assertions require a source that directly supports
that relationship. The `Entity assertion CSV` import screen is the review queue for
those independently sourced records.

Official source: [OFAC Sanctions List Service](https://ofac.treasury.gov/sanctions-list-service).
