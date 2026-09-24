"""Optional API-key enforcement plus a process-local rate limiter for the prototype."""
from collections import defaultdict, deque
from dataclasses import dataclass
import hmac
from time import monotonic

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .config import settings


@dataclass(frozen=True)
class InvestigatorIdentity:
    identifier: str
    role: str


def _identities() -> list[tuple[InvestigatorIdentity, str]]:
    """Parse `id:secret:role` entries. Empty config deliberately enables local demo mode."""
    entries = []
    for entry in filter(None, (item.strip() for item in settings.investigator_api_keys.split(","))):
        parts = entry.split(":", 2)
        if len(parts) != 3:
            continue
        entries.append((InvestigatorIdentity(parts[0], parts[2]), parts[1]))
    return entries


class RateLimiter:
    def __init__(self) -> None:
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, identity: str) -> bool:
        now = monotonic()
        bucket = self.events[identity]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= settings.requests_per_minute:
            return False
        bucket.append(now)
        return True


rate_limiter = RateLimiter()


def require_role(request: Request, *roles: str) -> None:
    """Enforce roles only when deployment API keys are configured."""
    if settings.investigator_api_keys and getattr(request.state, "role", "") not in roles:
        raise HTTPException(status_code=403, detail=f"This action requires one of: {', '.join(roles)}.")


async def security_middleware(request: Request, call_next):
    public_paths = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    if request.url.path in public_paths:
        return await call_next(request)
    identities = _identities()
    actor = request.headers.get("X-Investigator-ID", "local-development")
    if identities:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Bearer authentication is required."})
        supplied = authorization.removeprefix("Bearer ")
        match = next((identity for identity, secret in identities if hmac.compare_digest(secret, supplied)), None)
        if not match:
            return JSONResponse(status_code=401, content={"detail": "Invalid API key."})
        actor = match.identifier
        request.state.role = match.role
    request.state.actor = actor
    if not rate_limiter.allow(actor):
        return JSONResponse(status_code=429, content={"detail": "Request rate limit exceeded. Retry after one minute."})
    return await call_next(request)
