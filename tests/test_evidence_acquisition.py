"""Blueprint trust-core tests: metadata, coverage, and replay isolation."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.adapters import LegacyExplorerAdapter
from backend.domain import AssetRef, CanonicalTransfer
from backend.investigation_v2 import RecordedSnapshotRepository
from backend.models import Chain, TransferEvidence
from backend.tron import ProviderUnavailable


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
ROOT = "0x" + "a" * 40
DEST = "0x" + "b" * 40
CONTRACT = "0x" + "c" * 40
ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address=CONTRACT, decimals=6)


class MissingMetadataClient:
    async def outgoing_erc20_transfers(self, address, token_symbol, limit):
        return [TransferEvidence(
            transaction_hash="0x" + "d" * 64, source_address=ROOT, destination_address=DEST,
            token_symbol="USDT", token_contract=CONTRACT, amount=Decimal("10.5"), timestamp=NOW,
            block_number=1, confirmed=True, provider="fixture", retrieved_at=NOW,
        )], {"provider": "fixture", "retrieved_at": NOW.isoformat(), "pagination_truncated": False}


def test_adapter_refuses_amount_based_token_decimal_inference():
    with pytest.raises(ProviderUnavailable, match="missing verified token decimals"):
        asyncio.run(LegacyExplorerAdapter(Chain.ETHEREUM, MissingMetadataClient()).outgoing_transfers(ROOT, ASSET, 10))


def test_recorded_repository_is_network_isolated_and_uses_asset_identity():
    transfer = CanonicalTransfer(
        id="XFER-RECORDED", transaction_id="TX-RECORDED", chain=Chain.ETHEREUM,
        source_address=ROOT, destination_address=DEST, asset=ASSET, raw_amount=Decimal("10"),
        normalized_amount=Decimal("10"), timestamp=NOW, raw_evidence_id="EVID-RECORDED",
    )
    repository = RecordedSnapshotRepository([transfer])
    assert not hasattr(repository, "load_transaction")
    matches = asyncio.run(repository.outgoing_transfers(ROOT, ASSET, NOW, None))
    assert matches == [transfer]
    wrong_contract = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "d" * 40, decimals=6)
    assert asyncio.run(repository.outgoing_transfers(ROOT, wrong_contract, NOW, None)) == []

