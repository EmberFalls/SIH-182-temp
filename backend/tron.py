import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
import httpx

from .config import settings
from .models import TransferEvidence


class ProviderUnavailable(RuntimeError):
    pass


class TronGridClient:
    base_url = "https://api.trongrid.io"
    provider_name = "TronGrid"

    def __init__(self, api_key: str | None = None, timeout_seconds: float | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.trongrid_api_key
        self.timeout_seconds = timeout_seconds or settings.timeout_seconds
        self._cache: dict[tuple[str, str, int], tuple[float, list[TransferEvidence], dict]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def outgoing_trc20_transfers(self, address: str, token_symbol: str, limit: int) -> tuple[list[TransferEvidence], dict]:
        if not self.configured:
            raise ProviderUnavailable("TRONGRID_API_KEY is required for live TRON tracing.")
        cache_key = (address, token_symbol.upper(), limit)
        cached = self._cache.get(cache_key)
        if cached and monotonic() - cached[0] <= settings.provider_cache_seconds:
            transfers, provenance = cached[1], {**cached[2], "cache": "HIT"}
            return transfers, provenance
        retrieved_at = datetime.now(timezone.utc)
        url = f"{self.base_url}/v1/accounts/{address}/transactions/trc20"
        headers = {"TRON-PRO-API-KEY": self.api_key}
        params = {"only_confirmed": "true", "only_from": "true", "limit": min(limit, 100), "order_by": "block_timestamp,desc"}
        transfers: list[TransferEvidence] = []
        pages = 0
        request_attempts = 0
        cursor = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while pages < settings.max_provider_pages and len(transfers) < limit:
                page_params = {**params, "limit": min(100, limit - len(transfers))}
                if cursor:
                    page_params["fingerprint"] = cursor
                body, attempts = await self._get_page(client, url, headers, page_params)
                request_attempts += attempts
                pages += 1
                for item in body.get("data", []):
                    token = item.get("token_info") or {}
                    if token.get("symbol", "").upper() != token_symbol.upper():
                        continue
                    source, destination = item.get("from", ""), item.get("to", "")
                    if source != address or not destination:
                        continue
                    decimals = int(token.get("decimals") or 0)
                    transfers.append(TransferEvidence(
                        transaction_hash=item.get("transaction_id", ""), source_address=source, destination_address=destination,
                        token_symbol=token.get("symbol", token_symbol).upper(), token_contract=token.get("address", ""), amount=Decimal(str(item.get("value", "0"))) / (Decimal(10) ** decimals),
                        timestamp=datetime.fromtimestamp(int(item.get("block_timestamp", 0)) / 1000, tz=timezone.utc), block_number=item.get("block", None), confirmed=True, provider=self.provider_name, retrieved_at=retrieved_at,
                    ))
                cursor = (body.get("meta") or {}).get("fingerprint")
                if not cursor or not body.get("data"):
                    break
        provenance = {
            "provider": self.provider_name, "endpoint": url, "parameters": params,
            "retrieved_at": retrieved_at.isoformat(), "accepted_records": len(transfers), "pages_retrieved": pages,
            "provider_attempts": request_attempts, "pagination_truncated": bool(cursor), "cache": "MISS",
        }
        self._cache[cache_key] = (monotonic(), transfers, provenance)
        return transfers, provenance

    async def transaction_trc20_transfers(self, transaction_hash: str, token_symbol: str, token_contract: str | None, decimals: int) -> tuple[list[TransferEvidence], dict]:
        """Read confirmed TRC-20 Transfer events for one transaction only."""
        if not self.configured:
            raise ProviderUnavailable("TRONGRID_API_KEY is required for live TRON transaction-seeded tracing.")
        retrieved_at = datetime.now(timezone.utc)
        url = f"{self.base_url}/v1/transactions/{transaction_hash}/events"
        headers = {"TRON-PRO-API-KEY": self.api_key}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            body, attempts = await self._get_page(client, url, headers, {"only_confirmed": "true"})
        records = body.get("data", []) if isinstance(body.get("data"), list) else []
        transfers: list[TransferEvidence] = []
        for event in records:
            if event.get("event_name") != "Transfer":
                continue
            contract = str(event.get("contract_address") or "")
            if token_contract and contract != token_contract:
                continue
            result = event.get("result") or {}
            source = result.get("from") or result.get("0")
            destination = result.get("to") or result.get("1")
            raw_value = result.get("value") or result.get("2")
            if not source or not destination or raw_value is None:
                continue
            try:
                amount = Decimal(str(raw_value)) / (Decimal(10) ** decimals)
            except Exception:
                continue
            transfers.append(TransferEvidence(
                transaction_hash=transaction_hash, source_address=str(source), destination_address=str(destination),
                token_symbol=token_symbol.upper(), token_contract=contract, amount=amount,
                timestamp=datetime.fromtimestamp(int(event.get("block_timestamp", 0)) / 1000, tz=timezone.utc),
                block_number=int(event["block_number"]) if event.get("block_number") is not None else None,
                confirmed=True, provider=self.provider_name, retrieved_at=retrieved_at,
            ))
        provenance = {"provider": self.provider_name, "endpoint": url, "parameters": {"only_confirmed": "true"}, "retrieved_at": retrieved_at.isoformat(), "accepted_records": len(transfers), "provider_attempts": attempts, "transaction_hash": transaction_hash}
        return transfers, provenance
    async def _get_page(self, client: httpx.AsyncClient, url: str, headers: dict, params: dict) -> tuple[dict, int]:
        last_problem = "connection failure"
        for attempt in range(1, settings.provider_retry_attempts + 1):
            try:
                response = await client.get(url, headers=headers, params=params)
            except httpx.RequestError:
                response = None
                last_problem = "connection failure"
            if response is not None:
                if response.status_code == 429 or response.status_code >= 500:
                    last_problem = f"HTTP {response.status_code}"
                else:
                    try:
                        response.raise_for_status()
                        return response.json(), attempt
                    except (httpx.HTTPError, ValueError):
                        raise ProviderUnavailable(f"TronGrid returned an invalid HTTP {response.status_code} response.")
            if attempt < settings.provider_retry_attempts:
                await asyncio.sleep(settings.provider_retry_backoff_seconds * (2 ** (attempt - 1)))
        raise ProviderUnavailable(
            f"TronGrid retrieval failed after {settings.provider_retry_attempts} attempts ({last_problem})."
        )
