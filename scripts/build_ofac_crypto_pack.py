#!/usr/bin/env python3
"""Create an unreviewed crypto-address intelligence pack from OFAC's public SDN export.

The output is compatible with POST /v2/intelligence/import/assertions/csv. It does
not make VASP ownership claims. Every imported address remains UNREVIEWED, and is
classified as a high-risk SERVICE record until a local reviewer validates its use.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

DEFAULT_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.ZIP"
OUTPUT_COLUMNS = [
    "entity_name", "entity_type", "address", "chain", "role", "assertion_type",
    "source_name", "source_type", "trust_tier", "retrieved_at", "source_uri",
    "review_state", "risk_tags", "notes",
]


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].casefold()


def child_text(element: ET.Element, wanted: str) -> str:
    for child in element.iter():
        if local_name(child) == wanted.casefold() and child.text:
            return child.text.strip()
    return ""


def chain_for(address_type: str, address: str) -> str | None:
    kind = address_type.upper()
    if kind in {"ETH", "ETHEREUM"} and address.startswith("0x") and len(address) == 42:
        return "ETHEREUM"
    if kind in {"TRX", "TRON"} and address.startswith("T") and len(address) == 34:
        return "TRON"
    if kind in {"BTC", "XBT", "BITCOIN"}:
        return "BITCOIN"
    if kind in {"SOL", "SOLANA"}:
        return "SOLANA"
    return None


def records(xml: bytes, source_url: str, retrieved_at: str):
    root = ET.fromstring(xml)
    for entry in root.iter():
        if local_name(entry) not in {"sdnentry", "sanctionsentry"}:
            continue
        uid = child_text(entry, "uid") or child_text(entry, "uniqueid") or "unknown"
        name = " ".join(part for part in (child_text(entry, "firstName"), child_text(entry, "lastName")) if part).strip()
        name = name or child_text(entry, "name") or f"OFAC SDN {uid}"
        for identifier in entry.iter():
            if local_name(identifier) not in {"id", "identry", "identifier"}:
                continue
            address_type = child_text(identifier, "idType") or child_text(identifier, "type")
            address = child_text(identifier, "idNumber") or child_text(identifier, "number") or child_text(identifier, "value")
            chain = chain_for(address_type, address)
            if not chain:
                continue
            yield {
                "entity_name": name, "entity_type": "SERVICE", "address": address,
                "chain": chain, "role": "OTHER_SERVICE", "assertion_type": "VERIFIED",
                "source_name": "OFAC SDN public sanctions export", "source_type": "GOVERNMENT",
                "trust_tier": "A", "retrieved_at": retrieved_at, "source_uri": source_url,
                "review_state": "UNREVIEWED", "risk_tags": "OFAC_SANCTIONS|PUBLIC_SOURCE",
                "notes": f"Imported from public OFAC SDN export; source entry {uid}. Requires local review before operational use.",
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", default="intelligence_packs/ofac_crypto_review_queue.csv")
    args = parser.parse_args()
    with urlopen(args.url, timeout=60) as response:
        content = response.read()
    if content[:2] == b"PK":
        with ZipFile(BytesIO(content)) as archive:
            xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
            content = archive.read(xml_name)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows = list(records(content, args.url, retrieved_at))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} unreviewed public-risk assertions to {output}")


if __name__ == "__main__":
    main()
