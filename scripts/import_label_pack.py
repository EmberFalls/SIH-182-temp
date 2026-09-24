"""Import a reviewed JSON label pack without duplicating existing records."""
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.models import VaspLabelCreate  # noqa: E402
from backend.storage import Store  # noqa: E402


def main() -> None:
    label_path = PROJECT_ROOT / "demo" / "reviewed_ethereum_labels.json"
    records = json.loads(label_path.read_text(encoding="utf-8"))
    store = Store()
    added = 0
    for record in records:
        payload = VaspLabelCreate.model_validate(record)
        existing = store.labels_for_address(payload.address, payload.chain.value)
        if any(label.vasp_name == payload.vasp_name and label.source.url == payload.source.url for label in existing):
            continue
        store.add_label(payload)
        added += 1
    print(f"Imported {added} reviewed label(s).")


if __name__ == "__main__":
    main()
