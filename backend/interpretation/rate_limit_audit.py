"""Minimized audit policies specific to the LLM interpretation workflow."""

from __future__ import annotations

import logging

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEventType
from backend.audit.request_context import get_current_request_id
from backend.audit.services import record_security_event_best_effort

from .hmac_identifiers import build_llm_hmac_digest
from .transient_cache import get_llm_transient_cache


logger = logging.getLogger(__name__)


def record_llm_rate_limit_best_effort(
    *,
    actor: CustomUser,
    retry_after_seconds: int,
) -> bool:
    """Persist at most one rate-limit event per actor and reset window.

    Args:
        actor: Authenticated local user associated with the rejected request.
        retry_after_seconds: Bounded seconds until the quota becomes available.

    Returns:
        True only when a new audit event was successfully persisted. False
        means the event was already represented or an auxiliary system failed.
    """
    try:
        subject_digest = build_llm_hmac_digest(
            domain="llm-rate-limit-audit:v1",
            value=actor.id.hex,
        )
        transient_cache = get_llm_transient_cache()
        # A minute minimum prevents write amplification near a reset boundary;
        # one day caps retention even if a malformed exception reports more.
        marker_ttl = min(86_400, max(60, retry_after_seconds))
        marker_created = transient_cache.add(
            f"llm-rate-limit-audit-v1:{subject_digest}",
            True,
            timeout=marker_ttl,
        )
    except Exception:
        # If deduplication is unavailable, skip the database write instead of
        # allowing repeated rejected requests to amplify audit storage.
        logger.warning(
            "llm_rate_limit_audit outcome=degraded request_id=%s",
            get_current_request_id() or "none",
        )
        return False

    if not marker_created:
        return False

    # The marker remains if audit storage fails. Avoiding repeated inserts while
    # the database is unhealthy is preferable to retrying on every rejection.
    return record_security_event_best_effort(
        event_type=SecurityEventType.RATE_LIMITED,
        actor=actor,
    )
