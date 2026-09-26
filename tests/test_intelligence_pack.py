import importlib.util
from pathlib import Path


def _builder():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_ofac_crypto_pack.py"
    spec = importlib.util.spec_from_file_location("ofac_pack_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_ofac_pack_builder_creates_unreviewed_source_preserving_crypto_record():
    builder = _builder()
    xml = b"""<root><sdnEntry><uid>123</uid><firstName>Test</firstName><lastName>Entity</lastName><idList><id><idType>ETH</idType><idNumber>0x1111111111111111111111111111111111111111</idNumber></id></idList></sdnEntry></root>"""
    rows = list(builder.records(xml, "https://example.test/ofac.xml", "2026-09-27T00:00:00+00:00"))
    assert rows == [{
        "entity_name": "Test Entity", "entity_type": "SERVICE", "address": "0x1111111111111111111111111111111111111111",
        "chain": "ETHEREUM", "role": "OTHER_SERVICE", "assertion_type": "VERIFIED",
        "source_name": "OFAC SDN public sanctions export", "source_type": "GOVERNMENT", "trust_tier": "A",
        "retrieved_at": "2026-09-27T00:00:00+00:00", "source_uri": "https://example.test/ofac.xml",
        "review_state": "UNREVIEWED", "risk_tags": "OFAC_SANCTIONS|PUBLIC_SOURCE",
        "notes": "Imported from public OFAC SDN export; source entry 123. Requires local review before operational use.",
    }]
