from .models import CrossCaseAlert, GraphNode
from .storage import Store


class CrossCaseEngine:
    def __init__(self, store: Store) -> None:
        self.store = store

    def find_links(self, case_id: str, current_nodes: list[GraphNode]) -> list[CrossCaseAlert]:
        current_addresses = {node.address.lower() for node in current_nodes if node.role != "suspect"}
        alerts: list[CrossCaseAlert] = []
        if not current_addresses:
            return alerts
        for run in self.store.list_runs(exclude_case_id=case_id):
            other_nodes = run.get("nodes", [])
            shared = sorted(current_addresses & {str(node.get("address", "")).lower() for node in other_nodes if node.get("role") != "suspect"})
            if shared:
                alerts.append(CrossCaseAlert(
                    related_case_id=run["case_id"], related_run_id=run["run_id"], shared_addresses=shared,
                    severity="high" if len(shared) > 1 else "medium",
                    description="Observed non-suspect wallet infrastructure overlaps with a previous case trace. This is an investigative lead, not proof that cases share a beneficiary.",
                ))
        return alerts
