"""Tests for strict Groq requests, resilience, client reuse, and safe logs."""

from __future__ import annotations

import json
import logging
import math
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import groq
import httpx
from django.test import SimpleTestCase, override_settings

from ..provider import (
    GROQ_API_BASE_URL,
    LlmProviderBusyError,
    LlmProviderConfigurationError,
    LlmProviderError,
    LlmProviderRequestError,
    LlmProviderResponseError,
    LlmProviderTransientError,
    close_groq_client,
    estimate_request_tokens,
    get_groq_client,
    request_interpretation,
)
from ..rate_limits import LlmRateLimitExceeded
from .helpers import valid_output_payload


def completion_response(content: object) -> SimpleNamespace:
    """Create a minimal SDK-shaped completion response for adapter tests.

    Args:
        content: Value exposed as the assistant message content.

    Returns:
        A namespace with choices and safe aggregate usage fields.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(total_tokens=321),
    )


def sdk_error(
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> groq.APIStatusError:
    """Build a generic Groq status exception without real network traffic.

    Args:
        status_code: Synthetic HTTP response status.
        headers: Optional synthetic response headers.

    Returns:
        A configured SDK status exception.
    """
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )
    response = httpx.Response(
        status_code,
        request=request,
        headers=headers,
    )
    return groq.APIStatusError(
        "synthetic",
        response=response,
        body=None,
    )


class ManualClock:
    """Provide deterministic monotonic time for deadline tests."""

    def __init__(self) -> None:
        """Initialize the synthetic clock at zero seconds."""
        self.value = 0.0

    def __call__(self) -> float:
        """Return the current synthetic monotonic value.

        Returns:
            Current synthetic seconds.
        """
        return self.value

    def advance(self, seconds: float) -> None:
        """Advance synthetic time without sleeping.

        Args:
            seconds: Positive number of seconds to add.
        """
        self.value += seconds


class GroqProviderTests(SimpleTestCase):
    """Exercise provider behavior without sending external requests."""

    def setUp(self) -> None:
        """Create reusable guarded messages and mocked SDK hierarchy."""
        close_groq_client()
        self.messages = [
            {"role": "system", "content": "fixed guardrails"},
            {"role": "user", "content": "private-message-marker"},
        ]
        self.client = Mock()
        self.create = self.client.chat.completions.create
        self.attempt_reserver = Mock()

    def tearDown(self) -> None:
        """Close any shared client created by a lifecycle test."""
        close_groq_client()

    def test_operational_loggers_use_info_stdout_without_propagation(self) -> None:
        """Keep content-free LLM records visible once on container stdout."""
        logger_names = (
            "backend.interpretation.provider",
            "backend.interpretation.services",
            "backend.interpretation.throttles",
            "backend.interpretation.rate_limit_audit",
            "backend.audit.services",
        )

        for logger_name in logger_names:
            with self.subTest(logger_name=logger_name):
                operational_logger = logging.getLogger(logger_name)
                console_handlers = [
                    handler
                    for handler in operational_logger.handlers
                    if isinstance(handler, logging.StreamHandler)
                ]

                self.assertEqual(operational_logger.level, logging.INFO)
                self.assertFalse(operational_logger.propagate)
                self.assertEqual(len(console_handlers), 1)
                self.assertEqual(console_handlers[0].level, logging.INFO)
                self.assertIs(console_handlers[0].stream, sys.stdout)

    @override_settings(
        GROQ_API_KEY="test-key",
        LLM_MAX_CONCURRENT_PROVIDER_CALLS_PER_PROCESS=3,
    )
    @patch("backend.interpretation.provider.groq.Groq")
    @patch("backend.interpretation.provider.httpx.Client")
    def test_client_is_reused_closed_and_ignores_implicit_network_configuration(
        self,
        http_client_class: Mock,
        groq_class: Mock,
    ) -> None:
        """Reuse one secure connection pool and close it deterministically."""
        http_client = Mock()
        http_client_class.return_value = http_client
        sdk_client = Mock()
        sdk_client.is_closed.return_value = False
        groq_class.return_value = sdk_client

        first_client = get_groq_client()
        second_client = get_groq_client()
        close_groq_client()

        self.assertIs(first_client, sdk_client)
        self.assertIs(second_client, sdk_client)
        groq_class.assert_called_once()
        self.assertEqual(
            groq_class.call_args.kwargs["base_url"],
            GROQ_API_BASE_URL,
        )
        self.assertEqual(
            groq_class.call_args.kwargs["max_retries"],
            0,
        )
        self.assertIs(
            groq_class.call_args.kwargs["http_client"],
            http_client,
        )
        self.assertFalse(http_client_class.call_args.kwargs["trust_env"])
        self.assertFalse(
            http_client_class.call_args.kwargs["follow_redirects"]
        )
        sdk_client.close.assert_called_once()

    def test_gpt_oss_uses_only_strict_schema_and_hidden_reasoning(self) -> None:
        """Keep both allowed model controls fixed on the trusted backend."""
        self.create.return_value = completion_response(
            json.dumps(valid_output_payload())
        )

        for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            with self.subTest(model=model), override_settings(GROQ_MODEL=model):
                result = request_interpretation(
                    messages=self.messages,
                    approximate_tokens=500,
                    attempt_reserver=self.attempt_reserver,
                    client_factory=lambda: self.client,
                )

                self.assertEqual(result.kind, "pragmatic_interpretation")
                arguments = self.create.call_args.kwargs
                self.assertEqual(arguments["model"], model)
                self.assertTrue(
                    arguments["response_format"]["json_schema"]["strict"]
                )
                self.assertEqual(arguments["reasoning_format"], "hidden")
                self.assertEqual(arguments["reasoning_effort"], "medium")
                self.assertFalse(arguments["stream"])
                self.assertNotIn("n", arguments)
                self.assertNotIn("tools", arguments)
                self.assertNotIn("tool_choice", arguments)
                self.assertIsInstance(arguments["timeout"], httpx.Timeout)

    def test_token_estimate_pads_messages_and_strict_schema(self) -> None:
        """Reserve for the full request without claiming exact tokenization."""
        max_completion_tokens = 1200
        estimate = estimate_request_tokens(
            messages=self.messages,
            max_completion_tokens=max_completion_tokens,
        )
        messages_only_floor = (
            math.ceil(
                sum(len(message["content"]) for message in self.messages) / 4
            )
            + len(self.messages) * 8
            + max_completion_tokens
        )
        unicode_estimate = estimate_request_tokens(
            messages=[
                *self.messages,
                {"role": "user", "content": "😀" * 300},
            ],
            max_completion_tokens=max_completion_tokens,
        )

        self.assertGreater(estimate, messages_only_floor)
        self.assertGreater(unicode_estimate, estimate)

        with self.assertRaisesMessage(
            ValueError,
            "El presupuesto máximo de tokens de salida debe ser positivo.",
        ):
            estimate_request_tokens(
                messages=self.messages,
                max_completion_tokens=0,
            )

    def test_timeout_reserves_every_attempt_and_uses_full_jitter(self) -> None:
        """Reserve both real attempts around one deterministic retry delay."""
        timeout = groq.APITimeoutError(
            request=httpx.Request("POST", GROQ_API_BASE_URL)
        )
        self.create.side_effect = [
            timeout,
            completion_response(json.dumps(valid_output_payload())),
        ]
        sleeper = Mock()

        request_interpretation(
            messages=self.messages,
            approximate_tokens=500,
            attempt_reserver=self.attempt_reserver,
            client_factory=lambda: self.client,
            sleeper=sleeper,
            jitter_source=lambda _low, high: high,
        )

        self.assertEqual(self.create.call_count, 2)
        sleeper.assert_called_once_with(0.25)
        self.assertEqual(self.attempt_reserver.call_count, 2)

    def test_attempt_quota_is_not_reserved_without_capacity_or_client(
        self,
    ) -> None:
        """Avoid token and global quota reservations before provider readiness."""
        with patch("backend.interpretation.provider._PROVIDER_SEMAPHORE") as semaphore:
            semaphore.acquire.return_value = False

            with self.assertRaises(LlmProviderBusyError):
                request_interpretation(
                    messages=self.messages,
                    approximate_tokens=500,
                    attempt_reserver=self.attempt_reserver,
                    client_factory=lambda: self.client,
                )

            semaphore.release.assert_not_called()

        self.attempt_reserver.assert_not_called()

        with self.assertRaises(LlmProviderConfigurationError):
            request_interpretation(
                messages=self.messages,
                approximate_tokens=500,
                attempt_reserver=self.attempt_reserver,
                client_factory=Mock(
                    side_effect=LlmProviderConfigurationError(
                        "Configuración sintética no disponible."
                    )
                ),
            )

        self.attempt_reserver.assert_not_called()

    def test_attempt_quota_failure_prevents_the_external_call(self) -> None:
        """Preserve the quota error and stop before sending data to Groq."""
        self.attempt_reserver.side_effect = LlmRateLimitExceeded(
            retry_after_seconds=17
        )

        with self.assertRaises(LlmRateLimitExceeded) as raised:
            request_interpretation(
                messages=self.messages,
                approximate_tokens=500,
                attempt_reserver=self.attempt_reserver,
                client_factory=lambda: self.client,
            )

        self.assertEqual(raised.exception.retry_after_seconds, 17)
        self.attempt_reserver.assert_called_once_with()
        self.create.assert_not_called()

    @override_settings(LLM_MAX_ATTEMPTS=2)
    def test_retry_after_is_respected_or_rejected_by_the_server_cap(self) -> None:
        """Respect short provider delays and reject excessive worker blocking."""
        cases = (
            ("1.5", 1.5, False),
            ("8", None, True),
        )

        for retry_after, expected_delay, should_fail in cases:
            with self.subTest(retry_after=retry_after):
                self.create.reset_mock()
                self.create.side_effect = [
                    sdk_error(429, headers={"retry-after": retry_after}),
                    completion_response(json.dumps(valid_output_payload())),
                ]
                sleeper = Mock()

                if should_fail:
                    with self.assertRaises(LlmProviderTransientError):
                        request_interpretation(
                            messages=self.messages,
                            approximate_tokens=500,
                            attempt_reserver=self.attempt_reserver,
                            client_factory=lambda: self.client,
                            sleeper=sleeper,
                            jitter_source=lambda _low, high: high,
                        )
                    self.create.assert_called_once()
                    sleeper.assert_not_called()
                else:
                    request_interpretation(
                        messages=self.messages,
                        approximate_tokens=500,
                        attempt_reserver=self.attempt_reserver,
                        client_factory=lambda: self.client,
                        sleeper=sleeper,
                        jitter_source=lambda _low, high: high,
                    )
                    sleeper.assert_called_once_with(expected_delay)

    def test_retryable_statuses_stop_after_the_bounded_attempt_count(self) -> None:
        """Retry only closed transport and capacity status categories."""
        for status_code in (408, 409, 429, 498, 503):
            with self.subTest(status_code=status_code):
                self.create.reset_mock()
                self.create.side_effect = sdk_error(status_code)

                with self.assertRaises(LlmProviderTransientError):
                    request_interpretation(
                        messages=self.messages,
                        approximate_tokens=500,
                        attempt_reserver=self.attempt_reserver,
                        client_factory=lambda: self.client,
                        sleeper=Mock(),
                        jitter_source=lambda _low, high: high,
                    )

                self.assertEqual(self.create.call_count, 2)

    @override_settings(LLM_TOTAL_TIMEOUT_SECONDS=5)
    def test_total_budget_prevents_a_retry_after_a_slow_failed_attempt(
        self,
    ) -> None:
        """Stop before a retry when the first attempt consumes the deadline."""
        clock = ManualClock()
        timeout = groq.APITimeoutError(
            request=httpx.Request("POST", GROQ_API_BASE_URL)
        )

        def slow_failure(**_kwargs: object) -> object:
            """Consume the synthetic budget and raise a timeout.

            Args:
                **_kwargs: Provider arguments not needed by the test.

            Raises:
                groq.APITimeoutError: Always, after advancing the clock.
            """
            clock.advance(5)
            raise timeout

        self.create.side_effect = slow_failure

        with self.assertRaises(LlmProviderTransientError):
            request_interpretation(
                messages=self.messages,
                approximate_tokens=500,
                attempt_reserver=self.attempt_reserver,
                client_factory=lambda: self.client,
                sleeper=Mock(),
                clock=clock,
                jitter_source=lambda _low, high: high,
            )

        self.create.assert_called_once()

    def test_invalid_outputs_are_never_regenerated(self) -> None:
        """Reject missing, non-JSON, and schema-invalid output once."""
        invalid_contents: list[object] = ["not-json", None]
        extra = valid_output_payload()
        extra["unexpected"] = True
        invalid_contents.append(json.dumps(extra))

        for content in invalid_contents:
            with self.subTest(content=content):
                self.create.reset_mock()
                self.create.side_effect = None
                self.create.return_value = completion_response(content)

                with self.assertRaises(LlmProviderResponseError):
                    request_interpretation(
                        messages=self.messages,
                        approximate_tokens=500,
                        attempt_reserver=self.attempt_reserver,
                        client_factory=lambda: self.client,
                    )

                self.create.assert_called_once()

    def test_deterministic_statuses_use_closed_internal_error_categories(
        self,
    ) -> None:
        """Separate server configuration from request-contract rejections."""
        cases = (
            (400, LlmProviderConfigurationError),
            (401, LlmProviderConfigurationError),
            (403, LlmProviderConfigurationError),
            (404, LlmProviderConfigurationError),
            (413, LlmProviderRequestError),
            (422, LlmProviderRequestError),
        )

        for status_code, exception_type in cases:
            with self.subTest(status_code=status_code):
                self.create.reset_mock()
                self.create.side_effect = sdk_error(status_code)

                with self.assertRaises(exception_type):
                    request_interpretation(
                        messages=self.messages,
                        approximate_tokens=500,
                        attempt_reserver=self.attempt_reserver,
                        client_factory=lambda: self.client,
                    )

                self.create.assert_called_once()

    def test_unexpected_adapter_exception_is_sanitized_without_retry(self) -> None:
        """Prevent unexpected SDK details from reaching Django error responses."""
        self.create.side_effect = ValueError("private-message-marker")

        with self.assertRaises(LlmProviderError) as raised:
            request_interpretation(
                messages=self.messages,
                approximate_tokens=500,
                attempt_reserver=self.attempt_reserver,
                client_factory=lambda: self.client,
            )

        self.create.assert_called_once()
        self.assertNotIn("private-message-marker", str(raised.exception))
        self.assertEqual(
            str(raised.exception),
            "Se produjo un fallo inesperado en el adaptador del proveedor.",
        )

    def test_logs_exclude_content_and_report_attempt_accounting(self) -> None:
        """Log only closed operational metadata on a successful retry."""
        timeout = groq.APITimeoutError(
            request=httpx.Request("POST", GROQ_API_BASE_URL)
        )
        self.create.side_effect = [
            timeout,
            completion_response(json.dumps(valid_output_payload())),
        ]

        with self.assertLogs("backend.interpretation.provider", level="INFO") as logs:
            request_interpretation(
                messages=self.messages,
                approximate_tokens=500,
                attempt_reserver=self.attempt_reserver,
                client_factory=lambda: self.client,
                sleeper=Mock(),
                jitter_source=lambda _low, high: high,
            )

        rendered = " ".join(logs.output)
        self.assertIn("provider=groq", rendered)
        self.assertIn("accounted_tokens=821", rendered)
        self.assertIn("usage_source=provider_plus_estimate", rendered)
        self.assertIn("attempt_count=2", rendered)
        self.assertNotIn("private-message-marker", rendered)
        self.assertNotIn("Puede ser una petición", rendered)
