# Methodology

## Fund-flow accounting

The v2 engine uses Decimal values and a proportional-haircut allocation policy. Each outbound transfer receives the same tainted share as the known wallet ledger balance at that event. The engine retains unspent value and reports terminal and unresolved value separately. It never treats a graph path as proof of beneficial ownership.

## Entity intelligence

Address claims are stored as source-backed assertions. VERIFIED, RULE_INFERRED, and ML_INFERRED assertions are distinct. Review state and stale dates remain attached to each assertion.

## VASP attribution

Candidates aggregate actionable terminal receipts by entity. Attribution evidence is scored independently from flow materiality. The result may contain multiple VASPs or no actionable candidate.

## Deposit infrastructure

Deposit-like wallets are inferred from explainable receipt-to-sweep behavior and concentration toward reviewed VASP infrastructure. The created assertion remains unreviewed until a human reviewer accepts it.

## Cross-chain boundaries

A bridge continuation requires a reviewed route and an exact shared bridge message identifier connecting source and destination events. Similar amount, timing, or address patterns do not qualify. Unsupported or insufficiently proven bridge activity terminates as BRIDGE_UNRESOLVED.

## ML

ML is disabled by default. It can create only ML_INFERRED evidence and may be withheld when disabled or outside the validated evidence boundary. It cannot create a VERIFIED assertion.

## Reproducibility

Cases, versioned results, evidence manifests, source identifiers, algorithm versions, and data mode are persisted. Reports and local request drafts consume the same immutable result snapshot.