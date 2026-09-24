# VASP Trace

Evidence-first investigation workbench for SIH 182. The current milestone supports:

- case intake with an investigation time window and disputed token amount;
- confirmed TRON TRC-20 and Ethereum ERC-20 transfers from their public explorer APIs;
- bounded downstream tracing for USDT;
- source provenance, deterministic evidence manifests, and a tamper-evident hash;
- a reviewed VASP label registry that never treats an unsourced label as verified.
- conservative disputed-fund allocation, risk flags, cross-case leads, and bridge boundaries;
- draft-only SAHYOG request packets, audit records, background trace jobs, and PDF reports.
- an interactive local Cytoscape.js transaction graph with path highlighting, node/edge evidence inspection, and trace-frontier coverage gaps;
- a clearly marked `SIMULATED_DEMO` multi-hop scenario for judging and training, with operational drafting disabled.

## Run locally

1. Copy `.env.example` to `.env` and set `TRONGRID_API_KEY` and/or `ETHERSCAN_API_KEY`.
2. Install `pip install -r requirements.txt`.
3. Run `uvicorn backend.app:app --reload`, or double-click `run_demo.bat` on Windows.
4. Open `http://127.0.0.1:8000` for the investigation workbench.
5. Run `E:\Python\python.exe scripts\preflight.py` before a demonstration to confirm local configuration without printing any secret.

Live traces are marked `LIVE_CONFIRMED`. If a provider is unavailable or no label is supported by registry evidence, the service reports that limitation explicitly. The guided multi-hop training scenario is marked `SIMULATED_DEMO` in the UI, report data, and limitations; it cannot create a SAHYOG draft.

`INVESTIGATOR_API_KEYS` enables bearer-key access control in deployments. Leave it empty only for local development.

## Reviewed label packs

`demo/reviewed_ethereum_labels.json` contains a deliberately small public-source seed label. Import it with `E:\Python\python.exe scripts\import_label_pack.py`. Every production label must retain its source, reviewer, and expiry date; an unresolved or conflicting label is excluded from attribution.

## Demo flow

1. Select **Live public USDT attribution validation** and run a confirmed Ethereum trace to see a live receipt into the reviewed Binance endpoint.
2. Select **Load guided demo** to present a three-hop training path from suspect wallet through intermediary and deposit wallet to the reviewed endpoint.
3. Select a VASP or transfer in the graph to inspect its source evidence, provider provenance, and case-attributed amount.
4. Use **Challenge top evidence** to show how the conclusion depends on reviewed evidence.
5. Use **Verify trace receipt** to recompute the saved manifest hash. This verifies the saved record's integrity, not the truth of external provider data.
6. Mark a live case under review before preparing a local SAHYOG draft. The prototype never submits external requests.

The graph dependency is bundled locally; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Deployment

`deployment/docker-compose.yml` supplies a PostgreSQL 16 service and its evidence-schema migration. The present application store remains SQLite for local prototype runs; wire the supplied schema through a managed PostgreSQL repository before operational deployment.
