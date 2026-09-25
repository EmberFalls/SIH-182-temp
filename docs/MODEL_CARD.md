# Model Card - Phase 9 Baseline

## Task

- Wallet role classifier: `DEPOSIT_LIKE`, `SERVICE_LIKE`, `ORDINARY`, or `UNKNOWN`.
- Pair association baseline: scores whether an address behaves like an endpoint associated with one candidate VASP cluster.

## Data and labels

Feature snapshots are generated from normalized transfers at or before the declared snapshot time. Training rows retain the source assertion, source record, entity, chain, snapshot time, and feature hash.

Reviewed `VERIFIED` assertions are ground truth. `RULE_INFERRED` and `ML_INFERRED` assertions are weak labels and are excluded from the default role-model training set. Unlabeled wallets are excluded; they are never treated as negative examples.

## Model

The role baseline is deterministic softmax logistic regression implemented without an external ML runtime. Its artifact contains feature names, preprocessing means/scales, weights, hyperparameters, dataset version, and SHA-256 hash. The pair baseline is a versioned weighted score over direct cluster interaction, value share, and repeated sweeps.

Scores are not calibrated probabilities. A model inference is always recorded as `ML_INFERRED`; it cannot create or promote a `VERIFIED` assertion.

## Evaluation and safeguards

Use temporal and entity-holdout splits before enabling a model. Random splitting is useful for debugging only. Report precision, recall, F1, PR-AUC, ROC-AUC, and precision at the operational threshold. A model must beat the majority baseline on held-out data before it is considered for activation. The repository test fixture demonstrates these calculations only; it is not an operational performance claim. Record validated high-threshold precision from reviewed temporal and entity-holdout data before enabling any model.

The shipped configuration sets `ML_ENABLED=false`. When disabled, the inference adapter records a withheld result and the deterministic tracing, rule inference, and reviewed evidence workflow continue normally.

## Intended use

ML may add clearly marked supporting evidence for investigator review after validated deployment. It must not be used as the sole basis for a VASP attribution, beneficial-ownership conclusion, request draft, freeze, or external transmission.