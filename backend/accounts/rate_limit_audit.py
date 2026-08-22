"""Write-bounded audit policy for anonymous Google login throttling."""

import logging

from django.core.cache import cache

from backend.audit.models import SecurityEventType
from backend.audit.request_context import get_current_request_id
from backend.audit.services import record_security_event_best_effort


logger = logging.getLogger(__name__)
_AUDIT_MARKER_KEY = "accounts-google-login-rate-limit-audit:v1"


def record_google_login_rate_limit_best_effort(
    *,
    retry_after_seconds: int,
) -> bool:
    """Persist at most one anonymous login rate-limit event per reset window.

    Args:
        retry_after_seconds: Seconds calculated by the trusted DRF throttle.

    Returns:
        True only when a new audit event was successfully persisted.
    """
    try:
        marker_created = cache.add(
            _AUDIT_MARKER_KEY,
            True,
            timeout=min(86_400, max(60, retry_after_seconds)),
        )
    except Exception:
        # Skip persistence if deduplication is unavailable to prevent write amplification.
        logger.warning(
            "google_login_rate_limit_audit outcome=degraded request_id=%s",
            get_current_request_id() or "none",
        )
        return False

    if not marker_created:
        return False

    return record_security_event_best_effort(
        event_type=SecurityEventType.RATE_LIMITED,
        actor=None,
    )
