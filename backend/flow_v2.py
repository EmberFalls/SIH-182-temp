"""Event-driven disputed-fund allocation engine for account-based chains."""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Protocol

from .canonical import canonical_sha256
from .domain import (
    AllocationPolicyName,
    AssetRef,
    CanonicalTransfer,
    FlowAllocationV2,
    FlowSeed,
    FlowTerminalV2,
    FundFlowResultV2,
    HistoricalBalanceQuality,
    SeedPrecision,
    SeedType,
    TerminalReason,
    TracePolicyV2,
    WalletAssetStateSnapshot,
    normalize_address,
)


ZERO = Decimal("0")
UNRESOLVED_REASONS = {
    TerminalReason.MIXER_BOUNDARY,
    TerminalReason.BRIDGE_UNRESOLVED,
    TerminalReason.DEX_UNRESOLVED,
    TerminalReason.MAX_HOPS,
    TerminalReason.MAX_NODES,
    TerminalReason.TIME_BOUNDARY,
    TerminalReason.AMOUNT_THRESHOLD,
    TerminalReason.UNKNOWN,
}


class TransferRepository(Protocol):
    async def outgoing_transfers(self, address: str, asset: AssetRef, start_time: datetime, end_time: datetime | None) -> list[CanonicalTransfer]: ...


class HistoricalBalanceProvider(Protocol):
    async def state_at(self, address: str, asset: AssetRef, timestamp: datetime) -> WalletAssetStateSnapshot: ...


class FundAllocationPolicy(Protocol):
    name: AllocationPolicyName

    def allocate(self, state: "WalletState", transfer: CanonicalTransfer, parent_ids: list[str], depth: int) -> FlowAllocationV2: ...


@dataclass
class WalletState:
    address: str
    asset: AssetRef
    tainted: Decimal
    clean: Decimal
    unknown: Decimal
    quality: HistoricalBalanceQuality

    @property
    def total(self) -> Decimal:
        return self.tainted + self.clean + self.unknown

    def add_tainted(self, amount: Decimal) -> None:
        self.tainted += amount


class ProportionalHaircutPolicy:
    name = AllocationPolicyName.PROPORTIONAL_HAIRCUT

    def allocate(self, state: WalletState, transfer: CanonicalTransfer, parent_ids: list[str], depth: int) -> FlowAllocationV2:
        before_tainted, before_clean, before_unknown = state.tainted, state.clean, state.unknown
        total = state.total
        covered = min(transfer.normalized_amount, total)
        attributed = min(before_tainted, covered * (before_tainted / total)) if total > ZERO else ZERO
        state.tainted = max(ZERO, before_tainted - attributed)
        state.clean = max(ZERO, before_clean - covered * (before_clean / total)) if total > ZERO else before_clean
        state.unknown = max(ZERO, before_unknown - covered * (before_unknown / total)) if total > ZERO else before_unknown
        notes = ["Proportional haircut allocation: the covered outgoing value is apportioned by the tainted share of the known ledger balance."]
        if state.quality != HistoricalBalanceQuality.EXACT:
            notes.append(f"Historical balance quality is {state.quality.value}; allocation interpretation is limited.")
        if covered < transfer.normalized_amount:
            notes.append("Ledger balance did not cover the full observed transfer; only the covered amount was allocated.")
        allocation_id = f"ALLOC-{canonical_sha256({'transfer_id': transfer.id, 'parents': parent_ids, 'depth': depth, 'tainted': str(before_tainted), 'covered': str(covered)})[:24].upper()}"
        return FlowAllocationV2(
            id=allocation_id, transfer_id=transfer.id, source_address=transfer.source_address, destination_address=transfer.destination_address,
            depth=depth, timestamp=transfer.timestamp, policy=self.name, incoming_tainted_balance=before_tainted, incoming_clean_balance=before_clean,
            incoming_unknown_balance=before_unknown, transfer_amount=transfer.normalized_amount, ledger_covered_amount=covered,
            attributed_disputed_amount=attributed, parent_allocation_ids=parent_ids, methodology_notes=notes,
        )


@dataclass(order=True)
class _QueuedEvent:
    timestamp: datetime
    sequence: int
    kind: str = field(compare=False)
    payload: object = field(compare=False)


@dataclass
class _Arrival:
    address: str
    asset: AssetRef
    amount: Decimal
    timestamp: datetime
    depth: int
    parent_ids: list[str]


@dataclass
class _TransferEvent:
    transfer: CanonicalTransfer
    depth: int
    parent_ids: list[str]


TerminalClassifier = Callable[[CanonicalTransfer], TerminalReason | None]


class FundFlowEngineV2:
    """Deterministic, cycle-safe propagation of a disputed asset lot.

    The engine consumes a fixed provider snapshot. It tracks disputed value rather
    than plain graph reachability and keeps a lineage from every child allocation.
    """

    def __init__(self, transfer_repository: TransferRepository, balance_provider: HistoricalBalanceProvider, policy: FundAllocationPolicy | None = None, terminal_classifier: TerminalClassifier | None = None) -> None:
        self.transfer_repository = transfer_repository
        self.balance_provider = balance_provider
        self.policy = policy or ProportionalHaircutPolicy()
        self.terminal_classifier = terminal_classifier or (lambda _: None)

    async def trace(self, seed: FlowSeed, trace_policy: TracePolicyV2) -> FundFlowResultV2:
        if trace_policy.allocation_policy != self.policy.name:
            raise ValueError(f"Unsupported allocation policy: {trace_policy.allocation_policy.value}")
        if trace_policy.allowed_assets and self._asset_key(seed.asset) not in trace_policy.allowed_assets:
            raise ValueError("Seed asset is not allowed by this trace policy.")

        queue: list[_QueuedEvent] = []
        sequence = 0
        heapq.heappush(queue, _QueuedEvent(seed.timestamp, sequence, "arrival", _Arrival(seed.address, seed.asset, seed.amount, seed.timestamp, 0, [])))
        sequence += 1
        states: dict[tuple[str, str], WalletState] = {}
        scheduled_transfers: set[str] = set()
        scheduled_parent_ids: dict[str, list[str]] = {}
        processed_transfers: set[str] = set()
        allocations: list[FlowAllocationV2] = []
        terminals: list[FlowTerminalV2] = []
        warnings: list[str] = []
        node_addresses: set[tuple[str, str]] = set()

        while queue:
            event = heapq.heappop(queue)
            if trace_policy.end_time and event.timestamp > trace_policy.end_time:
                if event.kind == "arrival":
                    arrival = event.payload
                    assert isinstance(arrival, _Arrival)
                    terminals.append(self._terminal(arrival.address, arrival.amount, TerminalReason.TIME_BOUNDARY, arrival.depth, arrival.parent_ids, "Arrival falls after the trace policy end time."))
                continue

            if event.kind == "arrival":
                arrival = event.payload
                assert isinstance(arrival, _Arrival)
                address_key = (normalize_address(arrival.asset.chain, arrival.address), self._asset_key(arrival.asset))
                node_addresses.add(address_key)
                if len(node_addresses) > trace_policy.max_nodes:
                    terminals.append(self._terminal(arrival.address, arrival.amount, TerminalReason.MAX_NODES, arrival.depth, arrival.parent_ids, f"Trace node limit of {trace_policy.max_nodes} reached."))
                    continue
                state = states.get(address_key)
                if state is None:
                    snapshot = await self.balance_provider.state_at(arrival.address, arrival.asset, arrival.timestamp)
                    state = WalletState(address=address_key[0], asset=arrival.asset, tainted=snapshot.tainted_balance, clean=snapshot.clean_balance, unknown=snapshot.unknown_balance, quality=snapshot.historical_balance_quality)
                    states[address_key] = state
                state.add_tainted(arrival.amount)
                end_time = self._effective_end_time(arrival.timestamp, trace_policy)
                try:
                    outgoing = await self.transfer_repository.outgoing_transfers(arrival.address, arrival.asset, arrival.timestamp, end_time)
                except Exception as exc:
                    state.tainted = max(ZERO, state.tainted - arrival.amount)
                    terminals.append(self._terminal(arrival.address, arrival.amount, TerminalReason.UNKNOWN, arrival.depth, arrival.parent_ids, f"Provider retrieval failed: {exc}"))
                    warnings.append("PARTIAL_PROVIDER_DATA")
                    continue
                outgoing = sorted((item for item in outgoing if item.timestamp >= arrival.timestamp and (end_time is None or item.timestamp <= end_time)), key=lambda item: (item.timestamp, item.id))
                if not outgoing:
                    state.tainted = max(ZERO, state.tainted - arrival.amount)
                    terminals.append(self._terminal(arrival.address, arrival.amount, TerminalReason.NO_OUTGOING, arrival.depth, arrival.parent_ids, "No matching outbound transfer was available after this flow arrival."))
                    continue
                for transfer in outgoing:
                    if transfer.id in scheduled_transfers:
                        for parent_id in arrival.parent_ids:
                            if parent_id not in scheduled_parent_ids[transfer.id]:
                                scheduled_parent_ids[transfer.id].append(parent_id)
                        continue
                    if len(scheduled_transfers) >= trace_policy.max_edges:
                        terminals.append(self._terminal(arrival.address, arrival.amount, TerminalReason.MAX_NODES, arrival.depth, arrival.parent_ids, f"Trace edge limit of {trace_policy.max_edges} reached."))
                        break
                    scheduled_transfers.add(transfer.id)
                    scheduled_parent_ids[transfer.id] = list(arrival.parent_ids)
                    heapq.heappush(queue, _QueuedEvent(transfer.timestamp, sequence, "transfer", _TransferEvent(transfer, arrival.depth + 1, scheduled_parent_ids[transfer.id])))
                    sequence += 1
                continue

            transfer_event = event.payload
            assert isinstance(transfer_event, _TransferEvent)
            transfer = transfer_event.transfer
            if transfer.id in processed_transfers:
                continue
            processed_transfers.add(transfer.id)
            source_key = (normalize_address(transfer.chain, transfer.source_address), self._asset_key(transfer.asset))
            state = states.get(source_key)
            if state is None:
                continue
            parent_ids = scheduled_parent_ids.get(transfer.id, transfer_event.parent_ids)
            allocation = self.policy.allocate(state, transfer, parent_ids, transfer_event.depth)
            if allocation.attributed_disputed_amount <= ZERO:
                continue
            allocations.append(allocation)
            terminal_reason = self.terminal_classifier(transfer)
            if terminal_reason is not None:
                terminals.append(self._terminal(transfer.destination_address, allocation.attributed_disputed_amount, terminal_reason, transfer_event.depth, [allocation.id], "Terminal classification stopped further propagation."))
                continue
            if transfer_event.depth >= trace_policy.max_hops:
                terminals.append(self._terminal(transfer.destination_address, allocation.attributed_disputed_amount, TerminalReason.MAX_HOPS, transfer_event.depth, [allocation.id], f"Trace depth of {trace_policy.max_hops} hops reached."))
                continue
            if allocation.attributed_disputed_amount < trace_policy.min_attributed_amount or allocation.attributed_disputed_amount < seed.amount * trace_policy.min_attributed_share:
                terminals.append(self._terminal(transfer.destination_address, allocation.attributed_disputed_amount, TerminalReason.AMOUNT_THRESHOLD, transfer_event.depth, [allocation.id], "Attributed amount is below the configured materiality threshold."))
                continue
            heapq.heappush(queue, _QueuedEvent(transfer.timestamp, sequence, "arrival", _Arrival(transfer.destination_address, transfer.asset, allocation.attributed_disputed_amount, transfer.timestamp, transfer_event.depth, [allocation.id])))
            sequence += 1

        retained = sum((state.tainted for state in states.values()), ZERO)
        terminal_amount = sum((terminal.amount for terminal in terminals), ZERO)
        unresolved = sum((terminal.amount for terminal in terminals if terminal.reason in UNRESOLVED_REASONS), ZERO)
        if terminal_amount + retained > seed.amount:
            raise AssertionError("Fund-flow conservation invariant failed: output exceeds seed amount.")
        precision = SeedPrecision.EXACT if seed.seed_type == SeedType.TRANSACTION else SeedPrecision.APPROXIMATE
        return FundFlowResultV2(
            seed_id=seed.id, seed_timestamp=seed.timestamp, seed_amount=seed.amount, seed_precision=precision, allocation_policy=self.policy.name,
            allocations=allocations, terminals=terminals, retained_amount=retained, terminal_amount=terminal_amount,
            unresolved_amount=unresolved, warnings=sorted(set(warnings)), methodology={
                "allocation_policy": self.policy.name.value,
                "historical_balance_quality": "Balance state is supplied per address/asset snapshot; non-EXACT states are noted on allocations.",
                "conservation_rule": "terminal_amount + retained_amount must not exceed seed_amount.",
                "interpretation": "Proportional allocation is a deterministic accounting heuristic and does not identify individual token units or beneficial ownership.",
            },
        )

    @staticmethod
    def _asset_key(asset: AssetRef) -> str:
        return f"{asset.chain.value}:{asset.contract_address or asset.symbol}:{asset.symbol}"

    @staticmethod
    def _terminal(address: str, amount: Decimal, reason: TerminalReason, depth: int, parent_ids: list[str], detail: str) -> FlowTerminalV2:
        return FlowTerminalV2(address=address, amount=amount, reason=reason, depth=depth, parent_allocation_ids=parent_ids, detail=detail)

    @staticmethod
    def _effective_end_time(start: datetime, policy: TracePolicyV2) -> datetime | None:
        candidates = [item for item in [policy.end_time, start + timedelta(seconds=policy.max_time_delta_seconds) if policy.max_time_delta_seconds else None] if item is not None]
        return min(candidates) if candidates else None