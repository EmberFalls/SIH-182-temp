"""Conservative, case-specific allocation of the disputed token amount."""
from collections import defaultdict
from decimal import Decimal

from .models import FlowAllocation, FlowAnalysis, TransferEvidence


class FlowAllocator:
    def analyze(self, transfers: list[TransferEvidence], root_address: str, disputed_amount: Decimal | None) -> FlowAnalysis:
        ordered = sorted(transfers, key=lambda transfer: (transfer.timestamp, transfer.transaction_hash))
        root_outgoing = sum((transfer.amount for transfer in ordered if transfer.source_address == root_address), Decimal("0"))
        starting_amount = disputed_amount if disputed_amount is not None else root_outgoing
        available: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        available[root_address] = starting_amount
        endpoint_amounts: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        allocations: list[FlowAllocation] = []
        for transfer in ordered:
            attributable = min(transfer.amount, available[transfer.source_address])
            # A transfer observed before case funds reach the source is not attributed.
            available[transfer.source_address] -= attributable
            available[transfer.destination_address] += attributable
            endpoint_amounts[transfer.destination_address] += attributable
            allocations.append(FlowAllocation(
                transaction_hash=transfer.transaction_hash, source_address=transfer.source_address,
                destination_address=transfer.destination_address, transfer_amount=transfer.amount,
                attributed_amount=attributable,
            ))
        allocated_amount = sum((item.attributed_amount for item in allocations if item.source_address == root_address), Decimal("0"))
        return FlowAnalysis(
            starting_amount=starting_amount, allocated_amount=allocated_amount,
            unallocated_amount=max(Decimal("0"), starting_amount - allocated_amount), allocations=allocations,
            endpoint_amounts=dict(endpoint_amounts),
            method_note="Conservative FIFO allocation: an observed transfer receives attribution only up to the case-derived token balance available at its source. It does not prove beneficial ownership or identify individual token units.",
        )
