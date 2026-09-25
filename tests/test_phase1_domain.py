import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.adapters import LegacyExplorerAdapter
from backend.canonical import canonical_json_bytes, canonical_sha256
from backend.domain import AssetRef, CaseContextV2, DataMode, SeedType
from backend.models import Chain, TransferEvidence


NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
ROOT = "0x" + "A" * 40
DESTINATION = "0x" + "B" * 40


def test_canonical_hash_is_stable_across_decimal_and_key_order():
    left = {"amount": Decimal("10.000"), "at": NOW, "nested": {"a": 1, "b": 2}}
    right = {"nested": {"b": 2, "a": 1}, "at": datetime(2026, 9, 25, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))), "amount": Decimal("10")}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_transaction_seed_requires_transaction_hash_and_wallet_context_requires_wallet():
    asset = AssetRef(chain=Chain.ETHEREUM, symbol="usdt", contract_address="0x" + "C" * 40, decimals=6)
    assert asset.symbol == "USDT"
    with pytest.raises(ValueError, match="seed_tx_hash"):
        CaseContextV2(seed_type=SeedType.TRANSACTION, chain=Chain.ETHEREUM, asset=asset, disputed_amount=Decimal("1"), incident_time=NOW)
    context = CaseContextV2(seed_type=SeedType.WALLET_CONTEXT, chain=Chain.ETHEREUM, asset=asset, disputed_amount=Decimal("1"), incident_time=NOW, seed_wallet=ROOT, lookback_hours=4, data_mode=DataMode.RECORDED_REAL)
    assert context.data_mode == DataMode.RECORDED_REAL


class FakeEvmClient:
    async def outgoing_erc20_transfers(self, address, token_symbol, limit):
        return [TransferEvidence(
            transaction_hash="0x" + "D" * 64,
            source_address=ROOT,
            destination_address=DESTINATION,
            token_symbol="USDT",
            token_contract="0x" + "C" * 40,
            amount=Decimal("125.500000"),
            timestamp=NOW,
            block_number=123,
            confirmed=True,
            provider="Fake Etherscan",
            retrieved_at=NOW,
        )], {
            "provider": "Fake Etherscan",
            "endpoint": "https://provider.example/v2/api",
            "parameters": {"address": ROOT, "apikey": "must-not-be-carried"},
            "retrieved_at": NOW.isoformat(),
            "pagination_truncated": False,
        }


def test_legacy_evm_adapter_returns_canonical_decimal_safe_transfer_and_safe_evidence():
    result = asyncio.run(LegacyExplorerAdapter(Chain.ETHEREUM, FakeEvmClient()).outgoing_transfers(ROOT, "USDT", 10))
    assert result.complete is True
    assert result.warnings == []
    assert result.transfers[0].source_address == ROOT.lower()
    assert result.transfers[0].destination_address == DESTINATION.lower()
    assert result.transfers[0].normalized_amount == Decimal("125.500000")
    assert result.transfers[0].asset.symbol == "USDT"
    assert result.evidence.request_fingerprint is not None
    assert "apikey" not in result.evidence.metadata["parameters"]


class FakeTronClient:
    async def outgoing_trc20_transfers(self, address, token_symbol, limit):
        return [], {
            "provider": "Fake TronGrid",
            "endpoint": "https://provider.example/tron",
            "parameters": {"address": "T" + "A" * 33},
            "retrieved_at": NOW.isoformat(),
            "pagination_truncated": True,
        }


def test_legacy_tron_adapter_marks_truncated_response_partial():
    result = asyncio.run(LegacyExplorerAdapter(Chain.TRON, FakeTronClient()).outgoing_transfers("T" + "A" * 33, "USDT", 10))
    assert result.complete is False
    assert result.warnings == ["PARTIAL_PROVIDER_DATA"]
