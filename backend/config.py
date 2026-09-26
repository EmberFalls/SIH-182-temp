from dataclasses import dataclass
from pathlib import Path
import os


def _load_dotenv() -> None:
    """Load a project-local .env without adding a runtime dependency."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    trongrid_api_key: str = os.getenv("TRONGRID_API_KEY", "")
    etherscan_api_key: str = os.getenv("ETHERSCAN_API_KEY", "")
    investigator_api_keys: str = os.getenv("INVESTIGATOR_API_KEYS", "")
    database_path: str = os.getenv("DATABASE_PATH", "vasp_trace.db")
    database_url: str = os.getenv("DATABASE_URL", "")
    max_hops: int = max(1, min(int(os.getenv("TRACE_MAX_HOPS", "3")), 5))
    max_wallets: int = max(1, min(int(os.getenv("TRACE_MAX_WALLETS", "16")), 40))
    max_provider_pages: int = max(1, min(int(os.getenv("TRACE_MAX_PROVIDER_PAGES", "5")), 20))
    provider_cache_seconds: int = max(0, min(int(os.getenv("PROVIDER_CACHE_SECONDS", "300")), 3600))
    provider_retry_attempts: int = max(1, min(int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "4")), 8))
    provider_retry_backoff_seconds: float = max(0.25, min(float(os.getenv("PROVIDER_RETRY_BACKOFF_SECONDS", "1.0")), 10.0))
    etherscan_min_interval_seconds: float = max(0.0, min(float(os.getenv("ETHERSCAN_MIN_INTERVAL_SECONDS", "0.38")), 5.0))
    timeout_seconds: float = max(3.0, min(float(os.getenv("TRONGRID_TIMEOUT_SECONDS", "12")), 30.0))
    requests_per_minute: int = max(30, min(int(os.getenv("REQUESTS_PER_MINUTE", "120")), 1000))
    ml_enabled: bool = os.getenv("ML_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    ml_role_strong_threshold: float = max(0.5, min(float(os.getenv("ML_ROLE_STRONG_THRESHOLD", "0.90")), 1.0))
    ml_role_weak_threshold: float = max(0.5, min(float(os.getenv("ML_ROLE_WEAK_THRESHOLD", "0.70")), 1.0))


settings = Settings()
