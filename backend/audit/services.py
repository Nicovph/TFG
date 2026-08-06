"""Best-effort services for recording sanitized security audit events."""

from __future__ import annotations

import logging

from django.db import models

from .models import SecurityEvent, SecurityEventType
from .request_context import get_current_request_id


logger = logging.getLogger(__name__)


def record_security_event_best_effort(
    *,
    event_type: SecurityEventType,
    actor: models.Model | None,
) -> bool:
    """Persist one closed security event without affecting the main operation.

    Args:
        event_type: Closed audit category selected by trusted application code.
        actor: Optional authenticated local actor associated with the event.

    Returns:
        True when the event was persisted, or False when its type was invalid
        or the audit storage operation failed.
    """
    if not isinstance(event_type, SecurityEventType):
        # Never interpolate an invalid caller-controlled value into the log.
        logger.error(
            "security_event_record outcome=error event_type=invalid "
            "request_id=%s",
            get_current_request_id() or "none",
        )
        return False

    try:
        SecurityEvent.objects.record(
            event_type=event_type,
            actor=actor,
        )
    except Exception:
        # Exception details may contain database endpoints, SQL, or credentials.
        # The trusted event category and request ID are sufficient to alert and
        # correlate the audit failure without masking the primary application
        # result or disclosing the actor.
        logger.error(
            "security_event_record outcome=error event_type=%s request_id=%s",
            event_type.value,
            get_current_request_id() or "none",
        )
        return False

    return True
