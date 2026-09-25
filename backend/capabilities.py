"""Truthful, machine-readable chain capability declarations."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .models import Chain


class ChainCapabilityV2(BaseModel):
    chain: Chain
    display_name: str
    address_validation: str
    transfers: str
    fund_allocation: str
    labels: str
    cross_chain: str
    live_provider: str | None = None
    data_mode_support: list[str] = Field(default_factory=lambda: ["LIVE", "RECORDED_REAL", "SYNTHETIC"])
    notes: str


CAPABILITIES: tuple[ChainCapabilityV2, ...] = (
    ChainCapabilityV2(
        chain=Chain.ETHEREUM, display_name="Ethereum",
        address_validation="FULL", transfers="FULL", fund_allocation="FULL", labels="REGISTRY_ENABLED",
        cross_chain="EXPERIMENTAL", live_provider="Etherscan V2",
        notes="ERC-20 outgoing-transfer retrieval is available through the configured Etherscan V2-compatible provider.",
    ),
    ChainCapabilityV2(
        chain=Chain.TRON, display_name="TRON",
        address_validation="FULL", transfers="FULL", fund_allocation="FULL", labels="REGISTRY_ENABLED",
        cross_chain="NOT_IMPLEMENTED", live_provider="TronGrid",
        notes="TRC-20 outgoing-transfer retrieval is available through the configured TronGrid provider.",
    ),
    ChainCapabilityV2(
        chain=Chain.BNB_CHAIN, display_name="BNB Chain",
        address_validation="FULL", transfers="FULL", fund_allocation="FULL", labels="REGISTRY_ENABLED",
        cross_chain="EXPERIMENTAL", live_provider="Etherscan V2",
        notes="Uses the reusable EVM adapter with chain ID 56 and the configured Etherscan V2-compatible key.",
    ),
    ChainCapabilityV2(
        chain=Chain.POLYGON, display_name="Polygon PoS",
        address_validation="FULL", transfers="FULL", fund_allocation="FULL", labels="REGISTRY_ENABLED",
        cross_chain="EXPERIMENTAL", live_provider="Etherscan V2",
        notes="Uses the reusable EVM adapter with chain ID 137 and the configured Etherscan V2-compatible key.",
    ),
    ChainCapabilityV2(
        chain=Chain.BITCOIN, display_name="Bitcoin",
        address_validation="BASIC", transfers="NOT_IMPLEMENTED", fund_allocation="NOT_IMPLEMENTED", labels="REGISTRY_ENABLED",
        cross_chain="NOT_IMPLEMENTED",
        notes="Bitcoin requires a UTXO-specific evidence and allocation adapter; it is not traceable in this build.",
    ),
    ChainCapabilityV2(
        chain=Chain.SOLANA, display_name="Solana",
        address_validation="BASIC", transfers="NOT_IMPLEMENTED", fund_allocation="NOT_IMPLEMENTED", labels="REGISTRY_ENABLED",
        cross_chain="NOT_IMPLEMENTED",
        notes="Solana requires a dedicated account/token-transfer adapter; it is not traceable in this build.",
    ),
)


def capability_matrix() -> list[ChainCapabilityV2]:
    return list(CAPABILITIES)


def capability_for(chain: Chain) -> ChainCapabilityV2:
    return next(item for item in CAPABILITIES if item.chain == chain)