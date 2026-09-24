"""Run safe local checks before an SIH demonstration. No API keys are printed."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import settings
from backend.ethereum import EtherscanClient
from backend.tron import TronGridClient


async def main() -> None:
    checks = {
        "etherscan_key_configured": bool(settings.etherscan_api_key),
        "trongrid_key_configured": bool(settings.trongrid_api_key),
        "trace_max_hops": settings.max_hops,
        "trace_max_wallets": settings.max_wallets,
    }
    if settings.etherscan_api_key:
        checks["etherscan_adapter_ready"] = EtherscanClient().configured
    if settings.trongrid_api_key:
        checks["trongrid_adapter_ready"] = TronGridClient().configured
    print(checks)


if __name__ == "__main__":
    asyncio.run(main())
