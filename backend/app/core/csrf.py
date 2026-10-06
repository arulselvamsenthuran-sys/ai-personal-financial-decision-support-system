"""CSRF protection dependency for cookie-authenticated state-changing requests."""

from urllib.parse import urlparse
from fastapi import HTTPException, Request, status

from app.core.audit import audit_log
from app.core.config import settings


def verify_csrf(request: Request) -> None:
    """Verify Origin/Referer header for state-changing HTTP requests when using cookies.

    Only applies to state-changing methods (POST, PUT, PATCH, DELETE).
    Safe methods (GET, HEAD, OPTIONS) are exempt.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    # Only enforce if a session cookie is present
    session_cookie = request.cookies.get(settings.session_cookie_name)
    if not session_cookie:
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    source_url = origin or referer
    if not source_url:
        # Request with session cookie but missing Origin/Referer header on state-changing method
        client_ip = request.client.host if request.client else "unknown"
        audit_log(
            event_type="CSRF_REJECTED",
            status="BLOCKED",
            ip_address=client_ip,
            details={"reason": "Missing Origin and Referer headers", "path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site request forgery protection triggered: Missing origin metadata.",
        )

    # Validate source host against configured CORS origins
    parsed_source = urlparse(source_url)
    source_origin = f"{parsed_source.scheme}://{parsed_source.netloc}"

    allowed_origins = [o.rstrip("/") for o in settings.cors_origins]
    if source_origin not in allowed_origins:
        client_ip = request.client.host if request.client else "unknown"
        audit_log(
            event_type="CSRF_REJECTED",
            status="BLOCKED",
            ip_address=client_ip,
            details={"reason": f"Untrusted origin: {source_origin}", "path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site request forgery protection triggered: Untrusted origin.",
        )
