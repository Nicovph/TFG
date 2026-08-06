"""Service tests for transient minimisation and duplicate suppression."""

import json
from collections.abc import Callable
from typing import cast
from unittest.mock import ANY, Mock, patch

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from backend.accounts.models import CustomUser
from backend.preferences.models import UserPreferences

from ..contracts import LLMInterpretationOutput, OutputBusinessRuleError
from ..input_validation import (
    ContextSpeakerRelation,
    InterpretationMessageValidationError,
)
from ..provider import LlmProviderTransientError
from ..services import (
    DuplicateInterpretationRequest,
    InterpretationConfigurationError,
    InterpretationOutputRejected,
    interpret_message,
)
from .helpers import valid_output_payload


@override_settings(
    LLM_QUOTA_HMAC_KEY="service-unit-test-key-with-at-least-32-bytes",
)
class InterpretationServiceTests(TestCase):
    """Verify orchestration never persists or forwards common identifiers."""

    def setUp(self) -> None:
        """Create a minimal session-owned preference record and clear cache."""
        caches["default"].clear()
        self.user = CustomUser.objects.create_user(
            google_subject="interpretation-service-subject",
        )
        self.preferences = UserPreferences.objects.create(user=self.user)

    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_service_minimizes_before_provider_call(
        self,
        provider_mock: object,
        quota_mock: object,
    ) -> None:
        """Keep direct identifiers out of the provider message sequence."""
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )
        result = interpret_message(
            user=self.user,
            target_message="Escribe a private@example.org para responder.",
            previous_context="Antes escribió private@example.org.",
            previous_context_speaker=(
                ContextSpeakerRelation.DIFFERENT_FROM_TARGET_AUTHOR.value
            ),
            following_context="Después respondió other@example.org.",
            following_context_speaker=(
                ContextSpeakerRelation.SAME_AS_TARGET_AUTHOR.value
            ),
        )

        provider_messages = provider_mock.call_args.kwargs["messages"]
        serialized_messages = str(provider_messages)
        _instruction, serialized_payload = provider_messages[-1][
            "content"
        ].split("\n", maxsplit=1)
        prompt_payload = json.loads(serialized_payload)

        for identifier in ("private@example.org", "other@example.org"):
            self.assertNotIn(identifier, serialized_messages)

        self.assertIn("[EMAIL_1]", serialized_messages)
        self.assertIn("[EMAIL_2]", serialized_messages)
        self.assertEqual(
            prompt_payload["previous_context_speaker"],
            "different_from_target_author",
        )
        self.assertEqual(
            prompt_payload["following_context_speaker"],
            "same_as_target_author",
        )
        self.assertFalse(result.show_content_warning)
        quota_mock.assert_called_once()

    @patch("backend.interpretation.services.reserve_llm_provider_attempt_quota")
    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_attempt_reserver_attributes_tokens_to_the_authenticated_user(
        self,
        provider_mock: object,
        quota_mock: object,
        attempt_quota_mock: object,
    ) -> None:
        """Wire each provider attempt to the trusted UUID and token estimate."""

        def provider_response(**kwargs: object) -> LLMInterpretationOutput:
            """Invoke the service callback as one synthetic provider retry.

            Args:
                **kwargs: Server-owned provider arguments including the retry
                    reservation callback.

            Returns:
                A schema-valid synthetic provider response.
            """
            attempt_reserver = cast(
                Callable[[], None],
                kwargs["attempt_reserver"],
            )
            attempt_reserver()
            return LLMInterpretationOutput.model_validate(
                valid_output_payload()
            )

        provider_mock.side_effect = provider_response

        interpret_message(
            user=self.user,
            target_message="Mensaje sintético para reintento",
        )

        estimated_tokens = provider_mock.call_args.kwargs["approximate_tokens"]
        quota_mock.assert_called_once_with(user_id=self.user.id)
        attempt_quota_mock.assert_called_once_with(
            user_id=self.user.id,
            estimated_tokens=estimated_tokens,
        )

    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_service_revalidates_input_from_non_http_callers(
        self,
        provider_mock: Mock,
        quota_mock: Mock,
    ) -> None:
        """Reject invalid target or context before prompt construction."""
        invalid_text = "Texto con dirección \u202ecambiada."

        for field_name in (
            "target_message",
            "previous_context",
            "following_context",
        ):
            with self.subTest(field_name=field_name):
                request_values = {
                    "target_message": "Texto visible.",
                    "previous_context": "",
                    "following_context": "",
                    field_name: invalid_text,
                }

                with self.assertRaises(
                    InterpretationMessageValidationError
                ) as raised:
                    interpret_message(user=self.user, **request_values)

                self.assertEqual(
                    raised.exception.code,
                    "disallowed_control_or_format_characters",
                )

        target_length = settings.LLM_MAX_INPUT_CHARACTERS // 2
        previous_length = settings.LLM_MAX_INPUT_CHARACTERS - target_length

        with self.assertRaises(
            InterpretationMessageValidationError
        ) as raised:
            interpret_message(
                user=self.user,
                target_message="x" * target_length,
                previous_context="y" * previous_length,
                following_context="z",
            )

        self.assertEqual(raised.exception.code, "max_total_length")

        invalid_speaker_cases = (
            {
                "previous_context": "Mensaje anterior.",
                "previous_context_speaker": "persona_a",
            },
            {
                "following_context_speaker": (
                    ContextSpeakerRelation.SAME_AS_TARGET_AUTHOR.value
                ),
            },
        )

        for request_overrides in invalid_speaker_cases:
            with self.subTest(request_overrides=request_overrides):
                with self.assertRaises(ValueError):
                    interpret_message(
                        user=self.user,
                        target_message="Texto visible.",
                        **request_overrides,
                    )

        provider_mock.assert_not_called()
        quota_mock.assert_not_called()

    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_content_warning_is_derived_from_preferences_and_risk_signals(
        self,
        provider_mock: object,
        quota_mock: object,
    ) -> None:
        """Derive warning state without asking the provider to write a warning."""
        cases = (
            (True, "possible_aggression", True),
            (False, "possible_aggression", False),
            (True, "possible_indirect_language", False),
        )

        for index, (
            show_content_warnings,
            signal_kind,
            expected_warning,
        ) in enumerate(cases):
            with self.subTest(
                show_content_warnings=show_content_warnings,
                signal_kind=signal_kind,
            ):
                self.preferences.show_content_warnings = show_content_warnings
                self.preferences.save(update_fields=("show_content_warnings",))
                payload = valid_output_payload()
                payload["signals"] = [
                    {
                        "kind": signal_kind,
                        "explanation": "La señal está respaldada por el mensaje.",
                    }
                ]
                provider_mock.return_value = (
                    LLMInterpretationOutput.model_validate(payload)
                )

                result = interpret_message(
                    user=self.user,
                    target_message=f"Mensaje sintético {index}",
                )

                self.assertEqual(
                    result.show_content_warning,
                    expected_warning,
                )

        self.assertEqual(provider_mock.call_count, len(cases))
        self.assertEqual(quota_mock.call_count, len(cases))

    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_successful_duplicate_is_suppressed_without_result_cache(
        self,
        provider_mock: object,
        quota_mock: object,
    ) -> None:
        """Avoid immediate duplicate calls while retaining no interpretation."""
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )

        request_values = {
            "user": self.user,
            "target_message": "Cierra la ventana",
            "previous_context": "Hace frío.",
            "previous_context_speaker": "same_as_target_author",
            "following_context": "De acuerdo.",
            "following_context_speaker": "different_from_target_author",
        }
        interpret_message(**request_values)

        with self.assertRaises(DuplicateInterpretationRequest):
            interpret_message(**request_values)

        interpret_message(
            **{
                **request_values,
                "following_context_speaker": "same_as_target_author",
            }
        )

        self.assertEqual(provider_mock.call_count, 2)
        self.assertEqual(quota_mock.call_count, 2)

    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_failed_call_releases_duplicate_marker(
        self,
        provider_mock: object,
        quota_mock: object,
    ) -> None:
        """Allow a later user retry after a failed provider request."""
        provider_mock.side_effect = [
            LlmProviderTransientError("error temporal"),
            LLMInterpretationOutput.model_validate(valid_output_payload()),
        ]

        with self.assertRaises(LlmProviderTransientError):
            interpret_message(
                user=self.user,
                target_message="Mensaje transitorio",
            )

        interpret_message(
            user=self.user,
            target_message="Mensaje transitorio",
        )

        self.assertEqual(provider_mock.call_count, 2)
        self.assertEqual(quota_mock.call_count, 2)

    @patch("backend.interpretation.services.get_llm_transient_cache")
    @patch("backend.interpretation.services.build_messages")
    def test_early_failure_cleanup_never_masks_the_primary_error(
        self,
        build_messages_mock: Mock,
        get_cache_mock: Mock,
    ) -> None:
        """Cover prompt construction and make marker deletion best effort."""
        duplicate_cache = Mock()
        duplicate_cache.add.return_value = True
        duplicate_cache.delete.side_effect = RuntimeError(
            "private-cache-endpoint"
        )
        get_cache_mock.return_value = duplicate_cache
        build_messages_mock.side_effect = RuntimeError(
            "primary-service-failure"
        )

        with self.assertLogs(
            "backend.interpretation.services",
            level="WARNING",
        ) as captured:
            with self.assertRaisesMessage(
                RuntimeError,
                "primary-service-failure",
            ):
                interpret_message(
                    user=self.user,
                    target_message="Mensaje que no debe aparecer en logs.",
                )

        rendered_logs = " ".join(captured.output)
        self.assertIn("operation=delete", rendered_logs)
        self.assertNotIn("private-cache-endpoint", rendered_logs)
        self.assertNotIn("Mensaje que no debe aparecer", rendered_logs)

    @patch("backend.interpretation.services.get_llm_transient_cache")
    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_cache_add_outage_degrades_only_duplicate_suppression(
        self,
        provider_mock: Mock,
        quota_mock: Mock,
        get_cache_mock: Mock,
    ) -> None:
        """Keep PostgreSQL quotas authoritative when marker cache is down."""
        duplicate_cache = Mock()
        duplicate_cache.add.side_effect = RuntimeError(
            "private-cache-endpoint"
        )
        get_cache_mock.return_value = duplicate_cache
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )

        with self.assertLogs(
            "backend.interpretation.services",
            level="WARNING",
        ) as captured:
            result = interpret_message(
                user=self.user,
                target_message="Mensaje disponible aunque falle la caché.",
            )

        self.assertEqual(result.output.kind, "pragmatic_interpretation")
        quota_mock.assert_called_once_with(user_id=self.user.id)
        duplicate_cache.touch.assert_not_called()
        rendered_logs = " ".join(captured.output)
        self.assertIn("operation=add", rendered_logs)
        self.assertNotIn("private-cache-endpoint", rendered_logs)

    @override_settings(
        LLM_TOTAL_TIMEOUT_SECONDS=30,
        LLM_DUPLICATE_TTL_SECONDS=15,
    )
    @patch("backend.interpretation.services.get_llm_transient_cache")
    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_touch_failure_does_not_discard_a_valid_result(
        self,
        provider_mock: Mock,
        quota_mock: Mock,
        get_cache_mock: Mock,
    ) -> None:
        """Use separate in-flight and post-success marker lifetimes safely."""
        duplicate_cache = Mock()
        duplicate_cache.add.return_value = True
        duplicate_cache.touch.side_effect = RuntimeError(
            "private-cache-endpoint"
        )
        get_cache_mock.return_value = duplicate_cache
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )

        with self.assertLogs(
            "backend.interpretation.services",
            level="WARNING",
        ) as captured:
            result = interpret_message(
                user=self.user,
                target_message="Mensaje con resultado válido.",
            )

        self.assertEqual(result.output.kind, "pragmatic_interpretation")
        duplicate_cache.add.assert_called_once_with(
            ANY,
            True,
            timeout=45,
        )
        duplicate_cache.touch.assert_called_once_with(
            ANY,
            timeout=15,
        )
        quota_mock.assert_called_once_with(user_id=self.user.id)
        rendered_logs = " ".join(captured.output)
        self.assertIn("operation=touch", rendered_logs)
        self.assertNotIn("private-cache-endpoint", rendered_logs)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "llm-duplicate-default-test",
            },
            "llm_duplicate": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "llm-duplicate-alias-test",
            },
        },
        LLM_DUPLICATE_CACHE_ALIAS="llm_duplicate",
        LLM_REQUIRE_SHARED_DUPLICATE_CACHE=False,
    )
    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_duplicate_marker_uses_the_configured_cache_alias(
        self,
        provider_mock: Mock,
        quota_mock: Mock,
    ) -> None:
        """Keep marker placement independent from the default cache alias."""
        caches["default"].clear()
        caches["llm_duplicate"].clear()
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )

        interpret_message(
            user=self.user,
            target_message="Mensaje en alias cerrado.",
        )
        caches["default"].clear()

        with self.assertRaises(DuplicateInterpretationRequest):
            interpret_message(
                user=self.user,
                target_message="Mensaje en alias cerrado.",
            )

        provider_mock.assert_called_once()
        quota_mock.assert_called_once()

    @override_settings(LLM_REQUIRE_SHARED_DUPLICATE_CACHE=True)
    @patch("backend.interpretation.services.request_interpretation")
    def test_local_cache_is_rejected_when_shared_coordination_is_required(
        self,
        provider_mock: Mock,
    ) -> None:
        """Fail closed instead of claiming cross-process deduplication."""
        with self.assertRaises(InterpretationConfigurationError):
            interpret_message(
                user=self.user,
                target_message="Mensaje que requiere caché compartida.",
            )

        provider_mock.assert_not_called()

    @patch("backend.interpretation.services.validate_output_business_rules")
    @patch("backend.interpretation.services.reserve_llm_user_request_quota")
    @patch("backend.interpretation.services.request_interpretation")
    def test_business_rule_rejection_has_a_distinct_content_free_event(
        self,
        provider_mock: Mock,
        quota_mock: Mock,
        validate_mock: Mock,
    ) -> None:
        """Separate schema success from application-level output rejection."""
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )
        validate_mock.side_effect = OutputBusinessRuleError(
            "private-rejected-output"
        )

        with self.assertLogs(
            "backend.interpretation.services",
            level="WARNING",
        ) as captured:
            with self.assertRaises(InterpretationOutputRejected):
                interpret_message(
                    user=self.user,
                    target_message="Mensaje cuya salida se rechaza.",
                    previous_context="Contexto anterior sintético.",
                    following_context="Contexto posterior sintético.",
                )

        quota_mock.assert_called_once_with(user_id=self.user.id)
        self.assertEqual(
            validate_mock.call_args.kwargs["analyzed_message"],
            "Mensaje cuya salida se rechaza.",
        )
        rendered_logs = " ".join(captured.output)
        self.assertIn("error_type=business_rule", rendered_logs)
        self.assertNotIn("private-rejected-output", rendered_logs)
        self.assertNotIn("Mensaje cuya salida", rendered_logs)


@override_settings(
    LLM_QUOTA_HMAC_KEY="service-transaction-test-key-32-bytes",
)
class InterpretationTransactionBoundaryTests(TransactionTestCase):
    """Verify external HTTP work never extends the quota transaction."""

    def setUp(self) -> None:
        """Create committed user state and remove transient cache markers."""
        caches["default"].clear()
        self.user = CustomUser.objects.create_user(
            google_subject="interpretation-transaction-subject",
        )
        UserPreferences.objects.create(user=self.user)

    @patch("backend.interpretation.services.request_interpretation")
    def test_provider_call_runs_outside_the_quota_transaction(
        self,
        provider_mock: object,
    ) -> None:
        """Call the provider only after releasing database row locks."""

        def provider_response(**_kwargs: object) -> LLMInterpretationOutput:
            """Return valid output while observing the active transaction state.

            Args:
                **_kwargs: Server-owned provider arguments not needed by the test.

            Returns:
                A schema-valid synthetic provider response.
            """
            self.assertFalse(connection.in_atomic_block)
            return LLMInterpretationOutput.model_validate(
                valid_output_payload()
            )

        provider_mock.side_effect = provider_response

        result = interpret_message(
            user=self.user,
            target_message="Cierra la ventana",
        )

        self.assertEqual(result.output.kind, "pragmatic_interpretation")
        provider_mock.assert_called_once()
