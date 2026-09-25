import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.domain import (
    AssetRef,
    CanonicalTransfer,
    FlowSeed,
    HistoricalBalanceQuality,
    SeedType,
    TerminalReason,
    TracePolicyV2,
    WalletAssetStateSnapshot,
)
from backend.flow_v2 import FundFlowEngineV2
from backend.models import Chain


NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "c" * 40, decimals=6)
ROOT = "0x" + "a" * 40
A = "0x" + "b" * 40
B = "0x" + "d" * 40
C = "0x" + "e" * 40
VASP = "0x" + "f" * 40


def transfer(identifier, source, destination, amount, minute):
    return CanonicalTransfer(
        id=identifier,
        transaction_id=f"TX-{identifier}",
        chain=Chain.ETHEREUM,
        source_address=source,
        destination_address=destination,
        asset=ASSET,
        raw_amount=Decimal(amount),
        normalized_amount=Decimal(amount),
        timestamp=NOW + timedelta(minutes=minute),
        raw_evidence_id="EVID-1",
    )


class SnapshotRepository:
    def __init__(self, transfers):
        self.transfers = transfers

    async def outgoing_transfers(self, address, asset, start_time, end_time):
        return [item for item in self.transfers if item.source_address == address.lower() and item.asset == asset]


class SnapshotBalances:
    def __init__(self, clean=None):
        self.clean = {key.lower(): Decimal(value) for key, value in (clean or {}).items()}

    async def state_at(self, address, asset, timestamp):
        return WalletAssetStateSnapshot(
            address=address,
            asset=asset,
            clean_balance=self.clean.get(address.lower(), Decimal("0")),
            historical_balance_quality=HistoricalBalanceQuality.EXACT,
        )


def seed(amount="10000"):
    return FlowSeed(
        id="SEED-1",
        address=ROOT,
        asset=ASSET,
        amount=Decimal(amount),
        timestamp=NOW,
        seed_type=SeedType.TRANSACTION,
        source_transaction_id="TX-SEED",
        source_evidence_id="EVID-SEED",
    )


def run(transfers, *, clean=None, classifier=None, policy=None):
    return asyncio.run(FundFlowEngineV2(SnapshotRepository(transfers), SnapshotBalances(clean), terminal_classifier=classifier).trace(seed(), policy or TracePolicyV2(max_hops=5)))


def test_proportional_haircut_preserves_mixed_fund_accounting():
    result = run([transfer("ROOT-OUT", ROOT, A, "40000", 1)], clean={ROOT: "90000"})
    allocation = result.allocations[0]
    assert allocation.attributed_disputed_amount == Decimal("4000")
    assert allocation.incoming_clean_balance == Decimal("90000")
    assert result.terminal_amount == Decimal("4000")
    assert result.retained_amount == Decimal("6000")
    assert result.terminal_amount + result.retained_amount == result.seed_amount


def test_split_flow_tracks_each_terminal_and_retained_balance():
    result = run([
        transfer("ROOT-A", ROOT, A, "6000", 1),
        transfer("ROOT-B", ROOT, B, "2500", 2),
    ])
    assert [item.attributed_disputed_amount for item in result.allocations] == [Decimal("6000"), Decimal("2500")]
    assert result.terminal_amount == Decimal("8500")
    assert result.retained_amount == Decimal("1500")
    assert all(item.reason == TerminalReason.NO_OUTGOING for item in result.terminals)


def test_merge_is_not_double_counted_and_terminal_receipt_keeps_lineage():
    result = run([
        transfer("ROOT-A", ROOT, A, "2000", 1),
        transfer("ROOT-B", ROOT, B, "1000", 2),
        transfer("A-C", A, C, "2000", 3),
        transfer("B-C", B, C, "1000", 4),
        transfer("C-VASP", C, VASP, "3000", 5),
    ], classifier=lambda item: TerminalReason.VERIFIED_VASP if item.destination_address == VASP.lower() else None)
    vasp_allocations = [item for item in result.allocations if item.destination_address == VASP.lower()]
    assert len(vasp_allocations) == 1
    assert vasp_allocations[0].attributed_disputed_amount == Decimal("3000")
    assert result.terminal_amount == Decimal("3000")
    assert result.retained_amount == Decimal("7000")
    assert len(vasp_allocations[0].parent_allocation_ids) == 2
    assert result.terminals[0].parent_allocation_ids


def test_cycle_revisits_an_address_at_a_later_time_without_inflating_funds():
    result = run([
        transfer("ROOT-A", ROOT, A, "10000", 1),
        transfer("A-ROOT", A, ROOT, "10000", 2),
        transfer("ROOT-B", ROOT, B, "10000", 3),
    ])
    assert [item.transfer_id for item in result.allocations] == ["ROOT-A", "A-ROOT", "ROOT-B"]
    assert result.terminal_amount == Decimal("10000")
    assert result.retained_amount == Decimal("0")
    assert result.terminal_amount + result.retained_amount <= result.seed_amount


def test_same_snapshot_seed_and_policy_produce_same_result():
    transfers = [transfer("ROOT-A", ROOT, A, "5000", 1)]
    first = run(transfers)
    second = run(transfers)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")