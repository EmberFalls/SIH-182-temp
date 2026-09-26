import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
import httpx

from .config import settings
from .models import TransferEvidence
from .tron import ProviderUnavailable


class EvmScanClient:
    """Read-only ERC-20 collector for Etherscan V2-compatible EVM chains."""

    base_url = "https://api.etherscan.io/v2/api"
    provider_name = "Etherscan V2"
    chain_id = 1
    chain_name = "Ethereum"

    def __init__(self, api_key: str | None = None, timeout_seconds: float | None = None, chain_id: int | None = None, chain_name: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.etherscan_api_key
        self.timeout_seconds = timeout_seconds or settings.timeout_seconds
        if chain_id is not None:
            self.chain_id = chain_id
        if chain_name is not None:
            self.chain_name = chain_name
        self._cache: dict[tuple[str, str, int], tuple[float, list[TransferEvidence], dict]] = {}
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def outgoing_erc20_transfers(self, address: str, token_symbol: str, limit: int) -> tuple[list[TransferEvidence], dict]:
        if not self.configured:
            raise ProviderUnavailable("ETHERSCAN_API_KEY is required for live Ethereum tracing.")
        cache_key = (address.lower(), token_symbol.upper(), limit)
        cached = self._cache.get(cache_key)
        if cached and monotonic() - cached[0] <= settings.provider_cache_seconds:
            return cached[1], {**cached[2], "cache": "HIT"}
        retrieved_at = datetime.now(timezone.utc)
        params = {
            "chainid": self.chain_id, "module": "account", "action": "tokentx", "address": address,
            "startblock": 0, "endblock": 99999999, "page": 1, "offset": min(limit, 100), "sort": "desc", "apikey": self.api_key,
        }
        transfers: list[TransferEvidence] = []
        normalized_address = address.lower()
        pages = 0
        request_attempts = 0
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while pages < settings.max_provider_pages and len(transfers) < limit:
                page_params = {**params, "page": pages + 1, "offset": min(100, limit - len(transfers))}
                body, attempts = await self._get_page(client, page_params)
                request_attempts += attempts
                if body.get("status") == "0" and body.get("message") != "No transactions found":
                    raise ProviderUnavailable(f"Etherscan returned an error: {body.get('result')}")
                records = body.get("result", []) if isinstance(body.get("result"), list) else []
                pages += 1
                for item in records:
                    if (item.get("tokenSymbol", "").upper() != token_symbol.upper() or item.get("from", "").lower() != normalized_address or not item.get("to")):
                        continue
                    decimals = int(item.get("tokenDecimal") or 0)
                    transfers.append(TransferEvidence(
                        transaction_hash=item.get("hash", ""), source_address=item.get("from", "").lower(), destination_address=item.get("to", "").lower(),
                        token_symbol=item.get("tokenSymbol", token_symbol).upper(), token_contract=item.get("contractAddress", "").lower(), amount=Decimal(str(item.get("value", "0"))) / (Decimal(10) ** decimals),
                        timestamp=datetime.fromtimestamp(int(item.get("timeStamp", 0)), tz=timezone.utc), block_number=int(item["blockNumber"]) if item.get("blockNumber") else None,
                        confirmed=True, provider=f"{self.provider_name} ({self.chain_name})", retrieved_at=retrieved_at,
                    ))
                if len(records) < page_params["offset"]:
                    break
        provenance = {"provider": self.provider_name, "endpoint": self.base_url, "parameters": {key: value for key, value in params.items() if key != "apikey"},
                      "retrieved_at": retrieved_at.isoformat(), "accepted_records": len(transfers), "pages_retrieved": pages,
                      "provider_attempts": request_attempts,
                      "pagination_truncated": pages >= settings.max_provider_pages and len(transfers) >= limit, "cache": "MISS"}
        self._cache[cache_key] = (monotonic(), transfers, provenance)
        return transfers, provenance

    async def transaction_erc20_transfers(self, transaction_hash: str, token_symbol: str, token_contract: str | None, decimals: int) -> tuple[list[TransferEvidence], dict]:
        """Decode confirmed ERC-20 Transfer logs from one transaction receipt."""
        if not self.configured:
            raise ProviderUnavailable("ETHERSCAN_API_KEY is required for live EVM transaction-seeded tracing.")
        if not token_contract:
            raise ProviderUnavailable("A token contract address is required for EVM transaction-seeded tracing.")
        retrieved_at = datetime.now(timezone.utc)
        receipt_params = {"chainid": self.chain_id, "module": "proxy", "action": "eth_getTransactionReceipt", "txhash": transaction_hash, "apikey": self.api_key}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            receipt_body, receipt_attempts = await self._get_page(client, receipt_params)
            receipt = receipt_body.get("result")
            if not isinstance(receipt, dict) or not receipt.get("blockNumber"):
                raise ProviderUnavailable("EVM provider returned no confirmed transaction receipt for the requested hash.")
            block_params = {"chainid": self.chain_id, "module": "proxy", "action": "eth_getBlockByNumber", "tag": receipt["blockNumber"], "boolean": "false", "apikey": self.api_key}
            block_body, block_attempts = await self._get_page(client, block_params)
        block = block_body.get("result") or {}
        try:
            timestamp = datetime.fromtimestamp(int(str(block["timestamp"]), 16), tz=timezone.utc)
            block_number = int(str(receipt["blockNumber"]), 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("EVM provider returned an incomplete confirmed transaction receipt.") from exc
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        transfers: list[TransferEvidence] = []
        for log in receipt.get("logs") or []:
            topics = log.get("topics") or []
            if len(topics) < 3 or str(topics[0]).lower() != transfer_topic or str(log.get("address", "")).lower() != token_contract.lower():
                continue
            try:
                source = "0x" + str(topics[1])[-40:].lower()
                destination = "0x" + str(topics[2])[-40:].lower()
                amount = Decimal(int(str(log.get("data", "0x0")), 16)) / (Decimal(10) ** decimals)
            except (ValueError, ArithmeticError):
                continue
            transfers.append(TransferEvidence(
                transaction_hash=transaction_hash, source_address=source, destination_address=destination,
                token_symbol=token_symbol.upper(), token_contract=token_contract.lower(), amount=amount,
                timestamp=timestamp, block_number=block_number, confirmed=True,
                provider=f"{self.provider_name} ({self.chain_name})", retrieved_at=retrieved_at,
            ))
        provenance = {"provider": self.provider_name, "endpoint": self.base_url, "parameters": {"chainid": self.chain_id, "module": "proxy", "action": "eth_getTransactionReceipt", "txhash": transaction_hash}, "retrieved_at": retrieved_at.isoformat(), "accepted_records": len(transfers), "provider_attempts": receipt_attempts + block_attempts, "transaction_hash": transaction_hash, "receipt_block": block_number, "receipt_logs": receipt.get("logs") or []}
        return transfers, provenance
    async def _get_page(self, client: httpx.AsyncClient, params: dict) -> tuple[dict, int]:
        """Fetch one page with pacing and bounded retries, without leaking the API key."""
        last_problem = "connection failure"
        for attempt in range(1, settings.provider_retry_attempts + 1):
            async with self._request_lock:
                delay = settings.etherscan_min_interval_seconds - (monotonic() - self._last_request_at)
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    response = await client.get(self.base_url, params=params)
                    self._last_request_at = monotonic()
                except httpx.RequestError:
                    self._last_request_at = monotonic()
                    response = None
                    last_problem = "connection failure"

            if response is not None:
                if response.status_code == 429 or response.status_code >= 500:
                    last_problem = f"HTTP {response.status_code}"
                else:
                    try:
                        response.raise_for_status()
                        body = response.json()
                    except (httpx.HTTPError, ValueError):
                        raise ProviderUnavailable(f"Etherscan returned an invalid HTTP {response.status_code} response.")
                    result_text = str(body.get("result", "")).lower()
                    if body.get("status") == "0" and "rate limit" in result_text:
                        last_problem = "rate limit"
                    else:
                        return body, attempt

            if attempt < settings.provider_retry_attempts:
                await asyncio.sleep(settings.provider_retry_backoff_seconds * (2 ** (attempt - 1)))

        raise ProviderUnavailable(
            f"Etherscan retrieval failed after {settings.provider_retry_attempts} attempts ({last_problem})."
        )


class EtherscanClient(EvmScanClient):
    pass
