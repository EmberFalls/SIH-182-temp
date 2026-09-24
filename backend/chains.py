from .tron import ProviderUnavailable


class UnavailableChainClient:
    """Clear boundary for chains whose evidence adapter is not yet configured."""

    def __init__(self, chain_name: str) -> None:
        self.chain_name = chain_name

    async def outgoing_transfers(self, address: str, token_symbol: str, limit: int):
        raise ProviderUnavailable(f"{self.chain_name} live tracing is not configured. Add an approved chain provider before using this chain in an investigation.")
