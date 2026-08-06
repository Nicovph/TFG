"""Early cache-backed throttles for authenticated interpretation attempts."""

from __future__ import annotations

import logging
from typing import ClassVar
from uuid import UUID

from django.conf import settings
from django.core.cache.backends.base import BaseCache
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from backend.audit.request_context import get_current_request_id

from .hmac_identifiers import build_llm_hmac_digest
from .transient_cache import get_llm_transient_cache


logger = logging.getLogger(__name__)


class _InterpretationAttemptThrottle(SimpleRateThrottle):
    """Count all authenticated endpoint attempts under a pseudonymous key, it means,
    the check must be performed before validating the request body."""

    rate_setting: ClassVar[str]
    rate_period: ClassVar[str]
    scope: ClassVar[str]
    cache_format = "llm-attempt-throttle-v1:%(scope)s:%(ident)s"

    def __init__(self) -> None:
        """Resolve current settings while keeping cache failures non-fatal."""
        self._llm_cache: BaseCache | None

        try:
            self._llm_cache = get_llm_transient_cache()
        except Exception:
            # Mark the cache as unavailable.
            self._llm_cache = None
            self._log_cache_failure(operation="resolve")

        # DRF cache replacement.
        if self._llm_cache is not None:
            self.cache = self._llm_cache

        super().__init__()

    def get_rate(self) -> str:
        """Build the rate from validated server-owned configuration.

        Overrides the SimpleRateThrottle method that determines the 
        allowed rate.

        Returns:
            A DRF rate string for the throttle's configured period 
            (using the number/period format).
        """
        return f"{getattr(settings, self.rate_setting)}/{self.rate_period}"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        """Create a namespaced key without exposing the authenticated UUID.

        Args:
            request: Authenticated DRF request checked before throttling.
            view: Interpretation API view being protected.

        Returns:
            A cache key containing only a domain-separated HMAC, or None when
            the request has no authenticated UUID and cannot be identified.
        """
        user_id = getattr(request.user, "id", None)

        if not isinstance(user_id, UUID):
            return None

        # UUID.hex is canonical lowercase text without hyphens, so equivalent
        # UUID representations cannot create independent throttle subjects.
        subject_digest = build_llm_hmac_digest(
            domain="llm-interpretation-attempt:v1",
            value=user_id.hex,
        )
        # Apply the class template to form a namespaced key that never exposes the raw UUID.
        return self.cache_format % {
            "scope": self.scope,
            "ident": subject_digest,
        }

    def allow_request(self, request: Request, view: APIView) -> bool:
        """Apply the auxiliary throttle without making cache outages fatal.

        DRF's cache throttle is deliberately an early best-effort control: its
        operations are not atomic under concurrency. PostgreSQL quotas remain
        the authoritative distributed boundary before any provider call.

        Args:
            request: Authenticated request to count before parsing its body.
            view: Interpretation API view being protected.

        Returns:
            False when the configured attempt rate is exceeded, otherwise True.
            A cache failure degrades only this auxiliary layer and returns True.
        """
        # Prevents a cache miss from making the interpretation unavailable.
        if self._llm_cache is None:
            return True

        try:
            return super().allow_request(request, view)
        # It does not return `False` upon a technical failure, because that would 
        # turn a cache unavailability into a general denial of service.
        except Exception:
            self._log_cache_failure(operation="update")
            return True

    def _log_cache_failure(self, *, operation: str) -> None:
        """Emit a content-free operational warning for throttle degradation.

        Args:
            operation: Closed internal cache operation category.
        """
        logger.warning(
            "llm_attempt_throttle outcome=degraded operation=%s "
            "request_id=%s",
            operation,
            get_current_request_id() or "none",
        )


class InterpretationBurstThrottle(_InterpretationAttemptThrottle):
    """Limit short bursts of authenticated interpretation endpoint attempts."""

    rate_setting = "LLM_INTERPRETATION_ATTEMPTS_PER_MINUTE"
    rate_period = "minute"
    scope = "interpretation_burst"


class InterpretationSustainedThrottle(_InterpretationAttemptThrottle):
    """Limit sustained daily authenticated interpretation endpoint attempts."""

    rate_setting = "LLM_INTERPRETATION_ATTEMPTS_PER_DAY"
    rate_period = "day"
    scope = "interpretation_sustained"
