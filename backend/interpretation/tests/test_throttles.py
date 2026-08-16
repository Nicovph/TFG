"""Focused tests for privacy-minimised interpretation attempt throttles."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from django.test import SimpleTestCase, override_settings
from rest_framework.request import Request
from rest_framework.views import APIView

from ..throttles import InterpretationBurstThrottle


TEST_HMAC_KEY = "throttle-tests-only-key-material-32-bytes"
LOCAL_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "interpretation-throttle-default-tests",
    },
    "llm_attempts": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "interpretation-throttle-alias-tests",
    },
}


def _request_with_uuid() -> tuple[Request, str]:
    """Build the minimal authenticated request shape used by the throttle.

    Returns:
        A request-like object and its canonical UUID text for privacy checks.
    """
    user_id = uuid4()
    request = cast(
        Request,
        SimpleNamespace(user=SimpleNamespace(id=user_id)),
    )
    return request, str(user_id)


@override_settings(
    CACHES=LOCAL_CACHES,
    LLM_DUPLICATE_CACHE_ALIAS="default",
    LLM_REQUIRE_SHARED_DUPLICATE_CACHE=False,
    INTERPRETATION_HMAC_KEY=TEST_HMAC_KEY,
)
class InterpretationThrottleTests(SimpleTestCase):
    """Verify cache selection, pseudonymous keys, and safe degradation."""

    def test_cache_key_contains_hmac_but_not_authenticated_uuid(self) -> None:
        """Use a fixed-size digest instead of exposing the local user UUID."""
        request, raw_user_id = _request_with_uuid()
        throttle = InterpretationBurstThrottle()

        cache_key = throttle.get_cache_key(request, APIView())

        self.assertIsInstance(cache_key, str)
        typed_cache_key = cast(str, cache_key)
        self.assertTrue(
            typed_cache_key.startswith(
                "llm-attempt-throttle-v1:interpretation_burst:"
            )
        )
        self.assertRegex(
            typed_cache_key.rsplit(":", maxsplit=1)[-1],
            r"\A[0-9a-f]{64}\Z",
        )
        self.assertNotIn(raw_user_id, typed_cache_key)
        self.assertNotIn(raw_user_id.replace("-", ""), typed_cache_key)

    @override_settings(LLM_DUPLICATE_CACHE_ALIAS="llm_attempts")
    def test_throttle_uses_server_configured_cache_alias(self) -> None:
        """Keep early attempt counters in the selected transient cache."""
        throttle = InterpretationBurstThrottle()

        self.assertIs(throttle.cache, caches["llm_attempts"])

    @patch("backend.interpretation.throttles.get_llm_transient_cache")
    def test_cache_failures_allow_request_and_emit_sanitized_log(
        self,
        cache_resolver_mock: Mock,
    ) -> None:
        """Preserve availability without logging cache details or identity."""
        request, raw_user_id = _request_with_uuid()
        private_error = "redis://private-user:private-password@cache.internal"

        with self.subTest(operation="resolve"):
            cache_resolver_mock.side_effect = RuntimeError(private_error)

            with self.assertLogs(
                "backend.interpretation.throttles",
                level="WARNING",
            ) as captured:
                throttle = InterpretationBurstThrottle()
                allowed = throttle.allow_request(request, APIView())

            rendered_logs = " ".join(captured.output)
            self.assertTrue(allowed)
            self.assertIn("operation=resolve", rendered_logs)
            self.assertNotIn(private_error, rendered_logs)
            self.assertNotIn(raw_user_id, rendered_logs)

        with self.subTest(operation="update"):
            failing_cache = Mock(spec=BaseCache)
            failing_cache.get.side_effect = RuntimeError(private_error)
            cache_resolver_mock.side_effect = None
            cache_resolver_mock.return_value = failing_cache

            with self.assertLogs(
                "backend.interpretation.throttles",
                level="WARNING",
            ) as captured:
                throttle = InterpretationBurstThrottle()
                allowed = throttle.allow_request(request, APIView())

            rendered_logs = " ".join(captured.output)
            self.assertTrue(allowed)
            self.assertIn("operation=update", rendered_logs)
            self.assertNotIn(private_error, rendered_logs)
            self.assertNotIn(raw_user_id, rendered_logs)
