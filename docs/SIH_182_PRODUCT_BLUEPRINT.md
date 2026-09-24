# SIH 182 — VASP Trace Product and Implementation Blueprint

**Project:** Automated Attribution of Unknown Cryptocurrency Wallets to Nearest VASPs  
**Prototype target:** Smart India Hackathon screening and final demonstration  
**Primary user:** Law Enforcement Agency investigator using SAHYOG  
**Document status:** Implementation baseline  
**Last updated:** 24 September 2026

---

## 1. Product thesis

> Given a suspect cryptocurrency wallet, VASP Trace should find the nearest downstream VASP that received the funds of interest, show the exact evidence path and its uncertainty, and prepare a reviewable routing package for SAHYOG.

The product is not merely a wallet explorer, risk dashboard, or exchange-label lookup. Its value is the complete operational transition:

**Unknown wallet → confirmed transaction path → supported VASP attribution → investigator review → correct VASP request draft**

The prototype succeeds only when a judge can answer all five questions from one investigation screen:

1. Where did the investigated funds move?
2. Which portion of the observed flow can be linked to the case amount?
3. What is the nearest supported VASP?
4. Why does the system believe that attribution?
5. What can the investigator safely do next?

---

## 2. Precise interpretation of the problem statement

### 2.1 Input

An investigation contains:

- blockchain network;
- suspect wallet address;
- asset or token;
- disputed amount, when known;
- incident time window, when known;
- FIR or case reference;
- investigator notes and jurisdiction metadata.

### 2.2 Processing

The system must:

1. retrieve confirmed transactions from the selected chain;
2. construct a bounded directed transaction graph;
3. follow the relevant asset downstream through intermediary wallets;
4. conserve the case-derived amount while allocating it across branches;
5. match observed addresses against source-reviewed entity intelligence;
6. distinguish direct VASP receipts from inferred deposit-to-hot-wallet sweeps;
7. rank supported VASP candidates;
8. record retrieval provenance, coverage gaps, and failed provider calls;
9. preserve a reproducible evidence manifest;
10. create a draft request for investigator review.

### 2.3 Output

The system returns:

- an interactive fund-flow graph;
- one or more candidate VASPs;
- nearest hop distance;
- amount of case-derived funds attributed to each candidate;
- supporting transactions and labels;
- confidence and actionability status;
- risk and laundering-pattern observations;
- unresolved trace frontiers;
- an investigation report and evidence package;
- a SAHYOG-ready draft, only when the evidence gate is met.

### 2.4 Formal definition of “nearest VASP”

Let the observed transaction graph be `G = (V, E)` with suspect wallet `s`.

For every transfer edge `e`, the system calculates `a(e)`, the amount of case-derived funds conservatively allocated to that edge. A VASP endpoint `v` is eligible only when:

- a path exists from `s` to `v`;
- every transfer on the path is confirmed;
- `a(e) > 0` reaches `v`;
- the address or its ownership relationship has reviewed source evidence;
- the label is not expired, rejected, or in conflict.

The **nearest supported VASP** is the eligible endpoint with the minimum hop distance from `s`. If multiple endpoints exist at the same distance, they are ranked by evidence strength and attributable value.

The interface must show two separate concepts:

- **Nearest:** shortest supported path from the suspect.
- **Best supported:** strongest total evidence after confidence and coverage adjustments.

They may be different. The system must never silently merge those meanings.

---

## 3. What makes this prototype distinctive

### 3.1 Evidence-carrying graph

Every visible graph element carries its own proof:

- a transaction edge opens its hash, amount, asset, timestamp, block, provider, retrieval time, and allocated case amount;
- a labeled node opens its label source, reviewer, observation date, confidence tier, expiry, and conflict status;
- an inferred relationship shows the rule used and the evidence that satisfies it;
- an unresolved node explains why tracing stopped.

The graph is an investigation interface, not a decorative diagram.

### 3.2 Funds-of-interest overlay

Normal blockchain explorers show all activity. VASP Trace distinguishes:

- total transfer amount;
- case-attributed amount;
- unrelated wallet activity;
- remaining unallocated case amount.

This prevents a common analytical error: treating every transfer from a busy wallet as proceeds from the investigated case.

### 3.3 Evidence-gap frontier

The graph explicitly displays where knowledge ends:

- provider page limit reached;
- wallet query limit reached;
- rate limit or provider failure;
- chain adapter unavailable;
- cross-chain destination unresolved;
- no reviewed label available;
- incident window excluded a transfer.

This converts “no result” into a useful investigative next step.

### 3.4 Counterfactual challenge

An investigator or judge can remove a supporting label or transaction and ask:

> Does the attribution still hold without this evidence?

The system recomputes the conclusion and reports whether it remains supported or becomes unresolved. This is already partially implemented and should become a first-class graph interaction.

### 3.5 Actionability gate

Attribution and lawful action are separate states.

- **Observed:** the address or flow exists on-chain.
- **Attributed:** reviewed evidence associates an endpoint with a VASP.
- **Action-ready:** the evidence threshold, provenance, and review requirements are satisfied.
- **Drafted:** a request package has been created for human approval.

The system must not present a heuristic candidate as ready for freezing.

### 3.6 Trace receipt

Every completed trace receives:

- immutable run ID;
- query parameters and chain;
- provider and retrieval timestamps;
- accepted transaction set;
- limitations and failure records;
- label evidence versions;
- deterministic manifest hash.

This lets another investigator understand what was known at the time of analysis.

---

## 4. Reference project assessment

Reference reviewed: [SIH-2026-VASP-TRACE](https://github.com/harshalpatil2031-ui/SIH-2026-VASP-TRACE)

### 4.1 What its frontend does well

- Clear progression from investigator context to case queue to analysis workspace.
- Cytoscape.js graph with pan, zoom, reset, directed layout, labels, and selectable nodes.
- Strong node semantics for suspect wallets, mules, shared wallets, deposit addresses, and VASP hot wallets.
- Visible edge direction and amount labels.
- Dedicated node inspector drawer.
- Attribution explanation beside the graph.
- Cross-case correlation presented as part of the same investigation.
- SAHYOG and report actions positioned at the end of the workflow.
- Demo choreography suitable for a judging presentation.

### 4.2 What should not be copied as product truth

- Its demo generator can create a plausible path for an arbitrary wallet. Synthetic output must always be visibly marked `SIMULATED_DEMO` and must never resemble a live finding.
- Some demo addresses, balances, legal contacts, and transaction hashes are illustrative rather than source-backed.
- A known VASP label is not itself proof of a deposit sweep. Sweep evidence requires an observed onward transfer and supporting temporal or behavioral evidence.
- A confidence score is not a probability unless it has been calibrated against labelled ground truth.
- “Dispatch” must remain a draft or simulated action until official SAHYOG credentials and an approved integration contract exist.
- Legal templates must be configurable and reviewed by the sponsoring authority; they should not hard-code legal claims as product facts.
- CDN-only graph dependencies can fail during an offline SIH demonstration and should have a local fallback.

### 4.3 What our current system does well

- Live confirmed Ethereum and TRON retrieval.
- Etherscan-compatible support for Ethereum, BNB Chain, and Polygon.
- Provider pacing, retry, caching, partial-result handling, and provenance.
- Conservative case-fund allocation.
- Source-reviewed label registry with expiry, review, rejection, and conflict handling.
- Evidence-backed attribution only when case-derived funds reach a reviewed endpoint.
- Counterfactual evidence challenge.
- Cross-case shared-address detection.
- Risk and bridge observations.
- Deterministic evidence manifest and report generation.
- SAHYOG draft-only workflow.
- Persistent cases, notes, trace runs, and audit events.

### 4.4 Current critical gaps

- No interactive investigation graph.
- No node or transaction evidence inspector.
- No visible path selection or path-by-path attribution explanation.
- No visible unresolved trace frontier.
- Candidate ranking is shown as a list without graph context.
- Cross-case matches and bridge observations are not visually integrated.
- Demo data does not tell a complete multi-hop investigation story.
- The reviewed VASP label set is too small for a convincing prototype.
- The dashboard does not communicate chain coverage and live/demo provenance strongly enough.
- The workflow feels like an API console rather than an LEA workbench.

---

## 5. Product structure

The prototype will use three connected workspaces.

### 5.1 Workspace A — Case Command Centre

Purpose: choose or create the investigation.

Required elements:

- investigator and unit context;
- active case count and action-ready case count;
- case cards with FIR, chain, asset, amount, status, and latest finding;
- filters by status, chain, and jurisdiction;
- “New Investigation” intake;
- clearly separated `LIVE` and `SIMULATED_DEMO` cases;
- one-click opening of a prepared judging scenario.

### 5.2 Workspace B — Trace Investigation Workbench

This is the heart of the product.

#### Top command bar

- case ID and FIR;
- chain and asset;
- data mode badge;
- provider health;
- trace coverage indicator;
- run ID and retrieval time;
- run or expand trace action.

#### Left panel: scope and paths

- suspect wallet;
- disputed amount;
- incident window;
- maximum hops;
- transaction threshold;
- path list ordered by nearest supported VASP;
- unresolved branches;
- laundering-pattern filters;
- “show only case-attributed flow” toggle.

#### Centre panel: interactive graph

- Cytoscape.js canvas;
- directed layout from suspect to endpoints;
- pan, zoom, fit, centre, and fullscreen;
- selectable nodes and edges;
- path highlighting on hover or selection;
- edge width based on attributed amount;
- optional animation indicating direction, disabled when reduced motion is requested;
- legend and data-mode watermark;
- graph loading and partial-data states.

#### Right panel: evidence inspector

The panel changes with selection.

For a wallet node:

- full address and chain;
- role in this trace;
- hop distance;
- inbound and outbound case-attributed value;
- reviewed entity labels;
- label source and review history;
- other linked cases;
- risk observations;
- “challenge this label” action.

For a transfer edge:

- full transaction hash;
- source and destination;
- total amount and attributed amount;
- asset and token contract;
- timestamp and block;
- confirmation state;
- provider and retrieval time;
- explorer link;
- “challenge this transaction” action.

For an unresolved frontier:

- reason tracing stopped;
- last successful source;
- impact on the conclusion;
- suggested next step.

#### Bottom evidence rail

Tabs:

1. **Attribution:** ranked VASPs and proof factors.
2. **Transactions:** chronological evidence table.
3. **Cross-case:** shared wallets and related investigations.
4. **Risk patterns:** peeling, fan-out, rapid movement, mixer, bridge.
5. **Coverage:** providers, pages, limits, failures, and unresolved branches.
6. **Audit:** user actions and evidence challenges.

### 5.3 Workspace C — Action and Evidence Centre

Purpose: turn a supported result into a reviewable operational package.

Required elements:

- selected VASP and jurisdiction;
- actionability gate with passed and failed checks;
- receiving address and supporting transaction set;
- amount and time range;
- disclosure/preservation/freezing request draft;
- investigator review checklist;
- report preview and download;
- evidence package export;
- manifest-hash verification;
- explicit status: `DRAFT — NOT SENT` until official integration exists.

---

## 6. Graph visual language

| Element | Shape/colour | Meaning |
|---|---|---|
| Suspect wallet | Red circle | Investigation origin |
| Observed intermediary | Amber circle | Unlabelled downstream wallet |
| Shared cross-case wallet | Amber diamond with red border | Seen in another case |
| Deposit address | Purple pentagon | Supported VASP deposit relationship |
| VASP hot wallet | Green rounded rectangle | Reviewed VASP-controlled endpoint |
| Bridge | Blue hexagon | Reviewed bridge contract/service |
| Mixer | Dark red octagon | Reviewed mixer/tumbler service |
| Swap service | Indigo hexagon | Reviewed cross-chain or swap service |
| Unresolved frontier | Grey dashed circle | Trace stopped or evidence unavailable |
| Confirmed transfer | Solid directed edge | Confirmed on-chain transfer |
| Case-attributed flow | Bright overlay | Portion allocated to the case |
| Unrelated flow | Thin muted edge | Observed but not attributed to case |
| Supported sweep | Green double edge | Deposit address forwarded to reviewed hot wallet |
| Failed/partial retrieval | Dashed grey edge to frontier | Missing continuation evidence |

Every colour must also have a shape or label distinction for accessibility.

---

## 7. Evidence and attribution model

### 7.1 Evidence tiers

#### Tier A — Direct reviewed endpoint

Case-attributed funds directly reach an address with a current, approved VASP label.

Examples:

- reviewed exchange hot wallet;
- reviewed custodial service wallet;
- reviewed VASP-owned deposit address.

#### Tier B — Corroborated deposit sweep

Case-attributed funds reach an unlabelled or reviewed deposit address that subsequently forwards funds to a Tier A hot wallet. The relationship requires observed evidence, not a label assumption.

Required corroboration should include:

- onward transaction to a reviewed VASP hot wallet;
- chronological consistency;
- amount relationship within a documented tolerance;
- no conflicting entity label.

#### Tier C — Cluster or behavioural lead

The endpoint resembles a known VASP cluster based on repeated sweeps, common spend, service behaviour, or external intelligence, but ownership is not directly verified.

Tier C is an investigative lead. It is not sufficient for automated routing.

### 7.2 Confidence score

The score is an explainable prioritisation score, not a statistical probability.

`score = min(tier_cap, label + flow + proximity + corroboration + provenance + recency - penalties)`

Recommended components:

| Component | Maximum | Question answered |
|---|---:|---|
| Label evidence | 30 | How strong is the ownership evidence? |
| Case-flow continuity | 20 | How much of the case amount reaches this endpoint? |
| Hop proximity | 15 | How near is the endpoint to the suspect? |
| Sweep corroboration | 15 | Is deposit-to-hot-wallet behaviour observed? |
| Provider provenance | 10 | Is the path complete and reproducible? |
| Evidence recency | 10 | Is the label current? |

Penalties apply for:

- provider or pagination gaps;
- ambiguous branching;
- unresolved chain transition;
- stale evidence;
- conflicting labels;
- missing incident boundaries.

Recommended score caps:

- Tier A: 100;
- Tier B: 90;
- Tier C: 70.

### 7.3 Actionability rule

A candidate becomes `ACTION_READY` only if:

- it is Tier A or Tier B;
- its score meets the configured authority threshold;
- at least one confirmed case-attributed transaction supports it;
- its label is approved, current, and conflict-free;
- provider provenance is preserved;
- the trace is not contradicted by a successful challenge;
- an investigator explicitly reviews it.

---

## 8. Trace engine behaviour

### 8.1 Bounded traversal

- Breadth-first traversal prioritises the nearest reachable endpoints.
- Maximum hops, wallets, pages, time, and transfers are hard limits.
- Cycles and duplicate transactions are removed.
- Every stopped branch produces a frontier record.
- A later provider failure returns confirmed partial evidence.
- A failure at the first source returns a clear retrieval error.

### 8.2 Case-fund allocation

- Start with the disputed amount when provided.
- Otherwise, use the observed root outflow and clearly mark that assumption.
- Allocate funds chronologically.
- Never allocate more than the amount available at a wallet.
- Preserve branch splits and leftovers.
- Show transfer amount separately from attributed amount.
- Do not claim token-unit identity when using balance-based allocation.

### 8.3 Search stopping rules

Tracing may stop on a branch when:

- an action-ready VASP endpoint has been reached;
- the maximum hop count is reached;
- the branch has no confirmed outbound transfer for the asset;
- the available case-attributed balance is zero;
- a provider or query budget fails;
- a bridge transition cannot be resolved.

The user may explicitly expand a stopped branch.

---

## 9. Required response contract for the graph frontend

Each trace response should expose or derive the following structure:

```json
{
  "run": {
    "id": "RUN-...",
    "status": "COMPLETED",
    "data_mode": "LIVE_CONFIRMED",
    "created_at": "...",
    "manifest_sha256": "..."
  },
  "scope": {
    "chain": "ETHEREUM",
    "asset": "USDT",
    "root_address": "0x...",
    "disputed_amount": "3000",
    "max_hops": 3
  },
  "graph": {
    "nodes": [],
    "edges": [],
    "paths": [],
    "frontiers": []
  },
  "attribution": {
    "nearest_candidate_id": "...",
    "best_supported_candidate_id": "...",
    "candidates": []
  },
  "coverage": {
    "providers": [],
    "wallets_queried": 0,
    "pages_retrieved": 0,
    "partial": false,
    "limitations": []
  },
  "risk_alerts": [],
  "cross_case_alerts": [],
  "bridge_observations": []
}
```

### 9.1 Graph node fields

- `id`, `address`, `chain`;
- `role`;
- `hop`;
- `label`, `entity_kind`, `label_id`;
- `label_status`, `label_source`, `label_observed_at`;
- `case_inflow`, `case_outflow`;
- `risk_level`, `risk_tags`;
- `shared_case_ids`;
- `is_frontier`, `frontier_reason`.

### 9.2 Graph edge fields

- `id`, `transaction_hash`;
- `source`, `target`;
- `asset`, `token_contract`;
- `transfer_amount`, `attributed_amount`;
- `timestamp`, `block_number`, `confirmed`;
- `provider`, `retrieved_at`;
- `hop`, `path_ids`;
- `relationship`: `transfer`, `supported_sweep`, or `unresolved_transition`.

---

## 10. Implementation map

| Capability | Current state | Required work |
|---|---|---|
| Case management | Working | Redesign as command centre |
| Live Ethereum | Working | Expose provider coverage in UI |
| Live TRON | Working | Expose provider coverage in UI |
| BNB/Polygon | Adapter exists | Validate with real test cases |
| Bitcoin/Solana | Explicitly unavailable | Add later or present honestly |
| Graph construction | Backend nodes/transfers exist | Add paths, hops, frontiers, richer roles |
| Interactive graph | Missing | Build Cytoscape workbench |
| Node/edge inspector | Missing | Build evidence drawer |
| Conservative flow | Working | Visualise attributed vs total value |
| VASP labels | Review workflow works | Expand reviewed label pack |
| Deposit sweep | Incomplete | Implement observed sweep rule |
| Candidate scoring | Basic and working | Add evidence tiers and coverage penalties |
| Risk rules | Working baseline | Add graph highlighting and explanation |
| Cross-case | Working baseline | Add visual shared-wallet corridor |
| Counterfactual challenge | Working endpoint | Integrate into inspector and recompute view |
| Evidence manifest | Working | Add verification screen and receipt view |
| Report | Working endpoint | Redesign around path and limitations |
| SAHYOG draft | Working, draft-only | Build actionability checklist |
| Audit log | Stored | Add case audit timeline |

---

## 11. Build plan

### Phase 0 — Freeze the investigation contract

**Goal:** make backend and frontend agree on one evidence model.

Tasks:

- add hop and role metadata to graph nodes;
- produce stable edge IDs;
- derive paths to every VASP candidate;
- add trace-frontier records;
- expose data mode and coverage summary;
- add explorer URLs without exposing API keys;
- add an API schema snapshot test.

Exit criteria:

- one live Ethereum run can be converted into the graph response contract;
- the same transaction cannot appear twice;
- every candidate references at least one visible graph path.

### Phase 1 — Build the investigation workbench

**Goal:** make the trace understandable in ten seconds.

Tasks:

- restructure the frontend into command centre, workbench, and action centre;
- bundle Cytoscape.js locally with an optional CDN fallback;
- implement directed graph layout;
- implement node and edge styles;
- implement pan, zoom, fit, fullscreen, and legend;
- highlight a selected path;
- show attributed amount on edges;
- add node and edge evidence inspector;
- add loading, unresolved, partial, and error states;
- retain accessible table views for reports and non-visual review.

Exit criteria:

- selecting a Binance candidate highlights the complete suspect-to-Binance path;
- selecting an edge shows its complete transaction evidence;
- selecting a label shows its source and review state;
- partial traces visibly end in a frontier node.

### Phase 2 — Complete nearest-VASP reasoning

**Goal:** make the result defensible.

Tasks:

- calculate shortest supported path per VASP;
- distinguish nearest candidate from best-supported candidate;
- add Tier A direct endpoint logic;
- add Tier B observed deposit-sweep logic;
- add Tier C lead-only cluster logic;
- add coverage and ambiguity penalties;
- return a structured list of score factors;
- aggregate multiple deposits into one endpoint while retaining every supporting transaction;
- extend counterfactual challenge to recompute score factors and path status.

Exit criteria:

- no VASP is attributed from a name string or visual assumption alone;
- every score can be reconstructed from displayed factors;
- removing decisive evidence changes the result to unresolved.

### Phase 3 — Build the action and evidence centre

**Goal:** connect attribution to the SAHYOG workflow safely.

Tasks:

- create actionability checklist;
- add investigator review action and identity;
- add VASP routing metadata with evidence provenance;
- build draft preview;
- export evidence JSON and PDF;
- verify saved manifest hash;
- display `DRAFT — NOT SENT` consistently;
- add an audit timeline.

Exit criteria:

- an unresolved or Tier C result cannot create an action-ready draft;
- the report includes the path, transactions, label sources, limitations, and hash;
- a saved trace can be verified after restart.

### Phase 4 — Prepare authoritative demo scenarios

**Goal:** demonstrate breadth without misrepresenting synthetic evidence.

Required scenarios:

1. **Live Ethereum direct attribution**  
   Current public USDT source → reviewed Binance hot wallet.

2. **Live TRON unresolved trace**  
   Confirmed transfer retrieval with an explicit “no reviewed VASP label” outcome.

3. **Curated multi-hop deposit sweep**  
   Suspect → mule → deposit → reviewed hot wallet. Clearly marked `SIMULATED_DEMO` unless all transactions are real and independently verified.

4. **Cross-case shared wallet**  
   Two cases share an intermediary and produce a syndicate corridor alert.

5. **Evidence challenge**  
   Removing the decisive label causes attribution to become unresolved.

6. **Provider failure**  
   A controlled partial trace demonstrates the evidence-gap frontier.

Exit criteria:

- the judge can switch between live and demo cases without confusing their provenance;
- every demo scenario has a one-sentence learning objective;
- no simulated transaction is presented as live.

### Phase 5 — SIH hardening

**Goal:** make the prototype reliable in the judging environment.

Tasks:

- add one-click Windows launcher;
- add local static dependencies;
- add API-key and provider preflight checks;
- cache the prepared live trace for provider outages while clearly marking it as a saved run;
- create database backup and reset scripts;
- add browser smoke test for the complete demo path;
- add redaction mode for addresses and investigator identity;
- provide a short offline fallback video or screenshots;
- document exact limitations and future integrations.

Exit criteria:

- the complete prepared demo works after a fresh setup;
- temporary provider rate limits do not break the presentation;
- no secret appears in the browser, report, logs, or evidence package.

---

## 12. Four-minute judging demonstration

### 0:00–0:30 — Establish the operational problem

Open the command centre and select an investigation containing an unknown suspect wallet. Explain that the investigator cannot choose the correct VASP on SAHYOG from the wallet address alone.

### 0:30–1:30 — Run and understand the trace

Run the prepared live Ethereum trace. The graph grows from the suspect wallet. Select a transfer edge to show confirmed transaction evidence and the case-attributed amount.

### 1:30–2:20 — Defend the attribution

Select Binance. Highlight the nearest path. Open the label evidence, provider provenance, and score factors. Explain why this is supported and why the score is not presented as a probability.

### 2:20–2:50 — Challenge the system

Remove the decisive Binance label through the challenge control. Show that the system becomes unresolved rather than inventing another exchange. Restore the evidence.

### 2:50–3:25 — Show investigative intelligence

Open the curated multi-hop case. Show the deposit sweep and a shared intermediary found in another case. Explain that synthetic mode is clearly identified.

### 3:25–4:00 — Convert evidence into action

Open the action centre. Show the passed evidence gate, draft request, report, provenance, and manifest hash. End with the reduction in investigator steps:

**Trace, attribute, explain, correlate, and route from one case workspace.**

---

## 13. Questions judges are likely to ask

### “How do you know the address belongs to Binance?”

Show the reviewed label source, observation date, reviewer, status, and supporting on-chain receipt. Explain that an expired or conflicting label is excluded.

### “What happens when a wallet sends funds to many places?”

Show branch allocation. Only the amount available from the case balance is carried forward, and every destination is ranked separately.

### “Is the confidence score arbitrary?”

Show the named score factors, caps, and penalties. State that it is an explainable prioritisation score and not a calibrated probability.

### “Can this create false freezing requests?”

Show the actionability gate. Tier C leads, unresolved paths, conflict labels, and failed evidence challenges cannot become action-ready.

### “What if an API fails?”

Show the partial trace and evidence-gap frontier. Confirmed evidence remains visible, while the limitation is included in the report.

### “Is this really live?”

Show `LIVE_CONFIRMED`, provider name, retrieval timestamp, transaction hash, and explorer link. Then show that demo cases have a different visible mode.

### “How do you handle cross-chain movement?”

Explain that a reviewed bridge interaction is recorded on the source chain. Destination linkage requires destination-chain evidence and is never inferred from proximity alone.

### “What does SAHYOG integration currently do?”

State that the prototype prepares a structured, reviewable draft. Actual submission requires official API access, authentication, legal templates, and sponsor approval.

### “How is your solution different from a blockchain explorer?”

An explorer shows transactions. VASP Trace allocates the investigated funds, finds supported service endpoints, explains evidence and uncertainty, correlates cases, and prepares the correct operational route.

---

## 14. Prototype acceptance criteria

### Functional

- A user can create, open, update, and review a case.
- A live Ethereum and live TRON trace can be run from the interface.
- The graph renders all returned nodes and confirmed transfers.
- Candidate selection highlights the complete supporting path.
- Edge inspection displays transaction provenance.
- Node inspection displays label evidence and review state.
- Multiple receipts at one VASP consolidate into one candidate.
- Partial retrieval displays an evidence-gap frontier.
- Challenge controls visibly recompute the conclusion.
- Cross-case shared wallets appear in the graph and evidence rail.
- An action-ready candidate can produce a draft and report.
- An unsupported candidate cannot produce an action-ready draft.

### Evidence integrity

- Every transfer has a provider and retrieval timestamp.
- API keys are absent from provenance and logs.
- Every VASP candidate has a reviewed evidence source.
- Every candidate receives positive case-attributed value.
- Every limitation appears in the report.
- The saved manifest hash verifies after restart.
- Live, saved-live, and simulated data are visually distinct.

### Presentation

- The main result is understandable without opening API documentation.
- The graph remains usable at 20–40 visible nodes.
- The interface works at common laptop resolutions.
- A complete prepared demo finishes in under four minutes.
- Provider rate limits do not leave the interface in a permanent loading state.
- Empty, unresolved, partial, failed, and completed states are intentionally designed.

---

## 15. Data and integration priorities

### Immediate

- expand reviewed Ethereum and TRON VASP endpoints;
- store exact source URL, reviewer, observation time, and expiry;
- add explorer links for supported chains;
- validate BNB Chain and Polygon adapters;
- create a small reviewed service registry for bridges and mixers;
- build curated cases from reproducible evidence.

### Sponsor-dependent

- official SAHYOG API schema and credentials;
- FIU-IND or SAHYOG VASP directory;
- lawful nodal-contact directory;
- commercial blockchain intelligence API;
- LEA identity federation;
- retention, access-control, and audit requirements;
- approved legal notice templates.

### Later

- Bitcoin transaction adapter and UTXO allocation;
- Solana token-account resolution;
- destination-side bridge correlation;
- address-cluster inference with review workflow;
- streaming alerts for monitored cases;
- organisation-wide case graph.

---

## 16. Non-negotiable truth boundaries

- Never claim an individual’s identity from an address label.
- Never call a service a VASP without source evidence.
- Never call a transfer a deposit sweep solely because its destination has a VASP label.
- Never hide missing pages, failed providers, or unsupported chains.
- Never mix synthetic transactions into a live trace.
- Never present a prioritisation score as a probability.
- Never mark a request as sent without an authenticated SAHYOG response.
- Never include API keys in URLs, logs, reports, or exported evidence.
- Never imply that a manifest hash independently proves the truth of upstream data; it proves integrity of the saved record.

---

## 17. Immediate implementation sequence

The next development cycle should proceed in this order:

1. Add a frontend graph adapter for the current `TraceResult`.
2. Add hop metadata, stable graph IDs, paths, and frontier records to the backend.
3. Replace the present result page with the three-panel investigation workbench.
4. Add Cytoscape graph rendering and local dependency fallback.
5. Add the node/edge evidence inspector.
6. Connect candidate cards to graph path highlighting.
7. Integrate risk, cross-case, bridge, limitation, and provider coverage tabs.
8. Integrate the existing challenge endpoint into the inspector.
9. Build the actionability checklist and evidence centre.
10. Expand the reviewed label pack and prepare the six demonstration scenarios.
11. Run the full four-minute demonstration from a fresh environment.

The first implementation milestone is complete when the existing live Binance trace is rendered as an interactive, evidence-carrying path from the suspect wallet to the reviewed Binance endpoint.

