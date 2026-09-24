from .models import BridgeObservation, Chain, GraphNode, TransferEvidence


class CrossChainAnalyzer:
    def inspect(self, chain: Chain, transfers: list[TransferEvidence], nodes: list[GraphNode]) -> list[BridgeObservation]:
        labels = {node.address: node.label_evidence for node in nodes if node.label_evidence and node.label_evidence.entity_kind == "bridge"}
        observations: list[BridgeObservation] = []
        for transfer in transfers:
            label = labels.get(transfer.destination_address)
            if label:
                observations.append(BridgeObservation(
                    transaction_hash=transfer.transaction_hash, bridge_name=label.vasp_name, source_address=transfer.source_address,
                    bridge_address=transfer.destination_address, source_chain=chain, status="OBSERVED_SOURCE_BRIDGE_NOT_LINKED",
                    next_evidence_needed="A protocol-specific bridge message, attestation, or destination-chain mint/release event linked to this source transaction.",
                ))
        return observations
