from collections import Counter, defaultdict
from datetime import timedelta

from .models import GraphNode, RiskAlert, TransferEvidence


class RiskEngine:
    def analyze(self, transfers: list[TransferEvidence], nodes: list[GraphNode]) -> list[RiskAlert]:
        alerts: list[RiskAlert] = []
        outgoing: dict[str, list[TransferEvidence]] = defaultdict(list)
        incoming: dict[str, list[TransferEvidence]] = defaultdict(list)
        for transfer in transfers:
            outgoing[transfer.source_address].append(transfer)
            incoming[transfer.destination_address].append(transfer)
        bridge_or_mixer = {node.address: node.label_evidence for node in nodes if node.label_evidence}
        for address, label in bridge_or_mixer.items():
            if label.entity_kind == "mixer" and address in incoming:
                alerts.append(RiskAlert(code="mixer_interaction", severity="high", description=f"Observed transfer to sourced mixer label: {label.vasp_name}.", supporting_transactions=[item.transaction_hash for item in incoming[address]]))
            if label.entity_kind == "bridge" and address in incoming:
                alerts.append(RiskAlert(code="bridge_interaction", severity="medium", description=f"Observed transfer to sourced bridge label: {label.vasp_name}. A destination-chain claim requires bridge-message evidence.", supporting_transactions=[item.transaction_hash for item in incoming[address]]))
        for address, received in incoming.items():
            sent = sorted(outgoing.get(address, []), key=lambda item: item.timestamp)
            if not sent:
                continue
            earliest_gap = min((sent_item.timestamp - receive_item.timestamp for receive_item in received for sent_item in sent if sent_item.timestamp >= receive_item.timestamp), default=None)
            if earliest_gap is not None and earliest_gap <= timedelta(minutes=15):
                alerts.append(RiskAlert(code="rapid_movement", severity="medium", description="Funds moved onward within 15 minutes of an observed receipt.", supporting_transactions=[received[0].transaction_hash, sent[0].transaction_hash]))
        fanout = Counter(transfer.source_address for transfer in transfers)
        for address, count in fanout.items():
            if count >= 5:
                alerts.append(RiskAlert(code="high_fanout", severity="medium", description=f"Wallet sent to {count} observed destinations within the examined trace.", supporting_transactions=[item.transaction_hash for item in outgoing[address]]))
        chain_nodes = [address for address in incoming if len(incoming[address]) == 1 and len(outgoing.get(address, [])) == 1]
        if len(chain_nodes) >= 3:
            chain_txs = [outgoing[address][0].transaction_hash for address in chain_nodes]
            alerts.append(RiskAlert(code="peeling_chain", severity="medium", description="At least three intermediary wallets have one observed incoming and one observed outgoing transfer, consistent with a peeling-chain pattern.", supporting_transactions=chain_txs))
        return alerts
