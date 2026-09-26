"""Strict CSV parsers for investigator-supplied, replayable evidence packages."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal

from .domain import AssetRef, CanonicalTransfer, CaseCreateV2, RawEvidenceArtifact


REQUIRED_TRANSFER_COLUMNS = {
    "id", "transaction_id", "source_address", "destination_address",
    "raw_amount", "normalized_amount", "timestamp", "raw_evidence_id",
}


def parse_recorded_transfers_csv(csv_text: str, case: CaseCreateV2) -> list[CanonicalTransfer]:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    missing = REQUIRED_TRANSFER_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}.")
    transfers: list[CanonicalTransfer] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            asset = AssetRef(
                chain=case.context.chain,
                symbol=(row.get("asset_symbol") or case.context.asset.symbol),
                contract_address=(row.get("asset_contract_address") or case.context.asset.contract_address),
                decimals=int(row.get("asset_decimals") or case.context.asset.decimals),
                canonical_asset_id=row.get("canonical_asset_id") or case.context.asset.canonical_asset_id,
            )
            transfers.append(CanonicalTransfer(
                id=row["id"], transaction_id=row["transaction_id"], chain=case.context.chain,
                source_address=row["source_address"], destination_address=row["destination_address"], asset=asset,
                raw_amount=Decimal(row["raw_amount"]), normalized_amount=Decimal(row["normalized_amount"]),
                timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                transfer_type=row.get("transfer_type") or "token",
                log_index=int(row["log_index"]) if row.get("log_index") else None,
                event_index=int(row["event_index"]) if row.get("event_index") else None,
                raw_evidence_id=row["raw_evidence_id"],
            ))
        except Exception as exc:
            raise ValueError(f"CSV row {line_number}: {exc}") from exc
    if not transfers:
        raise ValueError("CSV contains no transfer rows.")
    return transfers