"""Lightweight in-memory sliding window rate limiter."""

from datetime import datetime, timezone
import threading
from typing import Dict, List
from fastapi import HTTPException, Request, status

from app.core.audit import audit_log


class RateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self, requests_per_window: int = 10, window_seconds: int = 60) -> None:
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_rate_limited(self, key: str) -> bool:
        """Check if key has exceeded allowed rate limit."""
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - self.window_seconds

        with self._lock:
            if key not in self._requests:
                self._requests[key] = []
            
            # Filter timestamps outside window
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]

            if len(self._requests[key]) >= self.requests_per_window:
                return True

            self._requests[key].append(now)
            return False

    def reset(self) -> None:
        """Clear rate limit store (useful for testing)."""
        with self._lock:
            self._requests.clear()


# Default auth rate limiter: 10 requests per minute per IP address
auth_rate_limiter = RateLimiter(requests_per_window=10, window_seconds=60)


def check_rate_limit(request: Request) -> None:
    """FastAPI dependency to enforce rate limiting on sensitive routes."""
    client_ip = request.client.host if request.client else "127.0.0.1"
    key = f"{request.url.path}:{client_ip}"

    if auth_rate_limiter.is_rate_limited(key):
        audit_log(
            event_type="RATE_LIMIT_EXCEEDED",
            ip_address=client_ip,
            status="BLOCKED",
            details={"path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )

