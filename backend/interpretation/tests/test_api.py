"""Focused adversarial tests for the protected interpretation API boundary."""

from __future__ import annotations

from unittest.mock import Mock, patch

from django.conf import settings
from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType
from backend.preferences.models import UserPreferences

from ..arasaac import (
    ArasaacAttribution,
    AvailablePictogram,
    MissingPictogram,
    VisualSupportResult,
)
from ..contracts import LLMInterpretationOutput
from ..provider import (
    LlmProviderBusyError,
    LlmProviderConfigurationError,
    LlmProviderError,
    LlmProviderResponseError,
    LlmProviderTransientError,
)
from ..rate_limits import (
    LlmQuotaReservationTooLarge,
    LlmRateLimitExceeded,
)
from ..services import (
    DuplicateInterpretationRequest,
    InterpretationConfigurationError,
    InterpretationOutputRejected,
    OffensiveLanguageOutputRejected,
    InterpretationResult,
)
from ..throttles import InterpretationBurstThrottle
from .helpers import valid_output_payload


def valid_service_result(
    *,
    show_content_warning: bool = False,
    visual_support: VisualSupportResult | None = None,
) -> InterpretationResult:
    """Return one validated application result for mocked API tests.

    Args:
        show_content_warning: Deterministic presentation flag to expose.
        visual_support: Optional validated ARASAAC response extension.

    Returns:
        A provider-independent application service result.
    """
    return InterpretationResult(
        output=LLMInterpretationOutput.model_validate(valid_output_payload()),
        show_content_warning=show_content_warning,
        visual_support=visual_support,
    )


@override_settings(
    INTERPRETATION_HMAC_KEY="interpretation-api-test-key-with-32-bytes-minimum",
)
class InterpretationApiTests(TestCase):
    """Verify the endpoint exposes a narrow and non-cacheable contract."""

    client_class = APIClient

    def setUp(self) -> None:
        """Create an authenticated user and reset transient marker state."""
        caches[settings.LLM_DUPLICATE_CACHE_ALIAS].clear()
        self.user = CustomUser.objects.create_user(
            google_subject="interpretation-api-subject",
        )
        UserPreferences.objects.create(user=self.user)
        self.url = reverse("api-interpretation")
        self.valid_request = {
            "target_message": "Si puedes, cierra la ventana.",
            "external_processing_acknowledged": True,
        }

    def assert_private_no_store(self, response: Response) -> None:
        """Assert the privacy cache policy without depending on token order.

        Args:
            response: DRF test response returned by the endpoint.
        """
        directives = {
            directive.strip()
            for directive in response["Cache-Control"].split(",")
        }
        self.assertIn("no-store", directives)
        self.assertIn("private", directives)
        self.assertEqual(response["Pragma"], "no-cache")

    @patch("backend.interpretation.views.interpret_message")
    def test_post_requires_authenticated_session_and_is_not_cacheable(
        self,
        service_mock: Mock,
    ) -> None:
        """Reject an anonymous request before invoking the application service."""
        response = self.client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["error"], "authentication_required")
        self.assertIn("iniciar sesión", response.data["message"])
        self.assert_private_no_store(response)
        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_success_returns_only_the_closed_non_cacheable_output(
        self,
        service_mock: Mock,
    ) -> None:
        """Return no provider configuration, identity, input, or acknowledgment."""
        service_mock.return_value = valid_service_result(
            show_content_warning=True
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {
                "interpretation",
                "clear_reformulation",
                "needs_more_context",
                "context_note",
                "signals",
                "visual_concepts",
                "show_content_warning",
            },
        )
        self.assertTrue(response.data["show_content_warning"])
        self.assert_private_no_store(response)

    @patch("backend.interpretation.views.interpret_message")
    def test_visual_support_opt_in_returns_the_validated_extension(
        self,
        service_mock: Mock,
    ) -> None:
        """Expose pictograms only to clients that request the new contract."""
        visual_support = VisualSupportResult(
            status="complete",
            items=[
                AvailablePictogram(
                    concept="cerrar ventana",
                    pictogram_id=1234,
                    label="cerrar la ventana",
                    image_url=(
                        "https://static.arasaac.org/pictograms/"
                        "1234/1234_300.png"
                    ),
                )
            ],
            message="",
            attribution=ArasaacAttribution(),
        )
        service_mock.return_value = valid_service_result(
            visual_support=visual_support
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"{self.url}?include=visual_support",
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {
                "interpretation",
                "clear_reformulation",
                "needs_more_context",
                "context_note",
                "signals",
                "visual_concepts",
                "show_content_warning",
                "visual_support",
            },
        )
        self.assertEqual(response.data["visual_support"]["status"], "complete")
        self.assertEqual(
            response.data["visual_support"]["items"][0]["pictogram_id"],
            1234,
        )
        self.assertEqual(
            response.data["interpretation"],
            valid_output_payload()["interpretation"],
        )
        self.assertTrue(service_mock.call_args.kwargs["include_visual_support"])
        self.assert_private_no_store(response)

    @patch("backend.interpretation.views.interpret_message")
    def test_visual_support_failure_keeps_text_and_http_200(
        self,
        service_mock: Mock,
    ) -> None:
        """Keep the interpretation usable when every pictogram is unavailable."""
        service_mock.return_value = valid_service_result(
            visual_support=VisualSupportResult(
                status="unavailable",
                items=[
                    MissingPictogram(
                        concept="cerrar ventana",
                        status="temporarily_unavailable",
                    )
                ],
                message=(
                    "Los pictogramas no se pudieron cargar. "
                    "La interpretación de texto sigue disponible."
                ),
                attribution=None,
            )
        )
        self.client.force_login(self.user)

        response = self.client.post(
            f"{self.url}?include=visual_support",
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["interpretation"],
            valid_output_payload()["interpretation"],
        )
        self.assertEqual(response.data["visual_support"]["status"], "unavailable")
        self.assertIn(
            "texto sigue disponible",
            response.data["visual_support"]["message"],
        )
        self.assert_private_no_store(response)

    @patch("backend.interpretation.views.interpret_message")
    def test_unknown_or_duplicate_query_parameters_are_rejected(
        self,
        service_mock: Mock,
    ) -> None:
        """Keep response negotiation closed without reflecting query values."""
        self.client.force_login(self.user)

        for query in (
            "unknown=value",
            "include=other",
            "include=visual_support&include=visual_support",
        ):
            with self.subTest(query=query):
                response = self.client.post(
                    f"{self.url}?{query}",
                    data=self.valid_request,
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertEqual(
                    response.data["error"],
                    "invalid_interpretation_request",
                )
                detail = response.data["fields"]["non_field_errors"][0]
                self.assertEqual(detail["code"], "invalid_query_parameters")
                self.assertNotIn(query, str(response.data))
                self.assert_private_no_store(response)

        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_unknown_provider_control_uses_a_generic_validation_envelope(
        self,
        service_mock: Mock,
    ) -> None:
        """Reject a representative provider control without reflecting its name."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            data={**self.valid_request, "model": "client-controlled"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "invalid_interpretation_request")
        self.assertEqual(
            response.data["fields"]["non_field_errors"][0],
            {
                "message": "La solicitud contiene campos no permitidos.",
                "code": "unknown_fields",
            },
        )
        self.assertNotIn("model", str(response.data))
        self.assertFalse(SecurityEvent.objects.exists())
        self.assert_private_no_store(response)
        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_unacknowledged_external_processing_returns_spanish_details(
        self,
        service_mock: Mock,
    ) -> None:
        """Expose a stable code and Spanish message for the required notice."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            data={
                **self.valid_request,
                "external_processing_acknowledged": False,
            },
            format="json",
        )

        detail = response.data["fields"][
            "external_processing_acknowledged"
        ][0]
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(detail["code"], "external_processing_not_acknowledged")
        self.assertIn("informado del procesamiento externo", detail["message"])
        self.assertFalse(SecurityEvent.objects.exists())
        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_normalizes_unicode_before_the_service_boundary(
        self,
        service_mock: Mock,
    ) -> None:
        """Pass one canonical NFKC representation into trusted services."""
        service_mock.return_value = valid_service_result()
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            data={
                **self.valid_request,
                "target_message": "Ｈｏｌａ， amigo.",
                "previous_context": "  Ａntes.\r\nOtra línea.  ",
                "previous_context_speaker": "different_from_target_author",
                "following_context": "  Ｄespués.  ",
                "following_context_speaker": "same_as_target_author",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once_with(
            user=self.user,
            target_message="Hola, amigo.",
            previous_context="Antes.\nOtra línea.",
            previous_context_speaker="different_from_target_author",
            following_context="Después.",
            following_context_speaker="same_as_target_author",
            include_visual_support=False,
        )

    @patch("backend.interpretation.views.interpret_message")
    def test_malformed_json_is_stable_and_not_cacheable(
        self,
        service_mock: Mock,
    ) -> None:
        """Hide parser detail while preserving the public 400 classification."""
        self.client.force_login(self.user)
        response = self.client.generic(
            "POST",
            self.url,
            data='{"message":',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "invalid_json")
        self.assertIn("JSON válido", response.data["message"])
        self.assertFalse(SecurityEvent.objects.exists())
        self.assert_private_no_store(response)
        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_unsupported_media_type_and_method_are_stable(
        self,
        service_mock: Mock,
    ) -> None:
        """Map pre-serializer DRF failures without exposing framework details."""
        self.client.force_login(self.user)
        unsupported = self.client.post(
            self.url,
            data="plain text",
            content_type="text/plain",
        )
        wrong_method = self.client.get(self.url)

        self.assertEqual(
            unsupported.status_code,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
        self.assertEqual(unsupported.data["error"], "unsupported_media_type")
        self.assertEqual(
            wrong_method.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(wrong_method.data["error"], "method_not_allowed")
        self.assert_private_no_store(unsupported)
        self.assert_private_no_store(wrong_method)
        service_mock.assert_not_called()

    @patch.object(InterpretationBurstThrottle, "wait", return_value=7)
    @patch.object(
        InterpretationBurstThrottle,
        "allow_request",
        return_value=False,
    )
    @patch("backend.interpretation.views.interpret_message")
    def test_attempt_throttle_rejects_before_parsing_the_body(
        self,
        service_mock: Mock,
        allow_request_mock: Mock,
        wait_mock: Mock,
    ) -> None:
        """Reject a malformed request through the early auxiliary throttle."""
        self.client.force_login(self.user)
        response = self.client.generic(
            "POST",
            self.url,
            data='{"message":',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            response.data["error"],
            "interpretation_attempt_rate_limited",
        )
        self.assertEqual(response["Retry-After"], "7")
        self.assertFalse(SecurityEvent.objects.exists())
        self.assert_private_no_store(response)
        allow_request_mock.assert_called_once()
        wait_mock.assert_called_once()
        service_mock.assert_not_called()

    @patch("backend.interpretation.views.interpret_message")
    def test_provider_response_failure_is_not_persisted_as_user_audit(
        self,
        service_mock: Mock,
    ) -> None:
        """Rely on provider telemetry for structurally invalid external output."""
        service_mock.side_effect = LlmProviderResponseError("salida privada")
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"], "invalid_provider_response")
        self.assertNotIn("salida privada", str(response.data))
        self.assertFalse(SecurityEvent.objects.exists())

    @patch("backend.interpretation.views.interpret_message")
    def test_business_rule_rejection_keeps_one_distinct_audit_event(
        self,
        service_mock: Mock,
    ) -> None:
        """Persist schema-valid output rejected by application safety rules."""
        service_mock.side_effect = InterpretationOutputRejected(
            "detalle privado de la salida"
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(
            response.data["error"],
            "invalid_interpretation_response",
        )
        self.assertNotIn("detalle privado", str(response.data))
        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
                actor=self.user,
            ).count(),
            1,
        )

    @patch("backend.interpretation.views.interpret_message")
    def test_hidden_offensive_output_explains_why_it_is_not_shown(
        self,
        service_mock: Mock,
    ) -> None:
        """Explain the honored preference without exposing rejected content."""
        service_mock.side_effect = OffensiveLanguageOutputRejected("private-output")
        self.client.force_login(self.user)

        response = self.client.post(self.url, data=self.valid_request, format="json")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.data["error"], "offensive_language_hidden")
        self.assertEqual(
            response.data["message"],
            "La respuesta generada incluía lenguaje ofensivo y tu preferencia "
            "está configurada para ocultarlo. No se ha mostrado ese contenido. "
            "Puedes intentarlo de nuevo.",
        )
        self.assertNotIn("private-output", str(response.data))
        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
                actor=self.user,
            ).count(),
            1,
        )

    @patch("backend.interpretation.views.interpret_message")
    def test_operational_provider_failures_do_not_duplicate_telemetry(
        self,
        service_mock: Mock,
    ) -> None:
        """Map operational failures without creating persistent user events."""
        self.client.force_login(self.user)
        cases = (
            (
                LlmProviderBusyError("capacidad interna"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "interpretation_temporarily_unavailable",
            ),
            (
                LlmProviderTransientError("timeout privado"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "interpretation_temporarily_unavailable",
            ),
            (
                LlmProviderError("error privado"),
                status.HTTP_502_BAD_GATEWAY,
                "interpretation_provider_error",
            ),
        )

        for index, (exception, expected_status, expected_error) in enumerate(cases):
            with self.subTest(exception=type(exception).__name__):
                service_mock.side_effect = exception
                response = self.client.post(
                    self.url,
                    data={
                        **self.valid_request,
                        "target_message": f"Mensaje operativo {index}",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data["error"], expected_error)

        self.assertFalse(SecurityEvent.objects.exists())

    @patch("backend.interpretation.views.interpret_message")
    def test_configuration_invariants_return_one_stable_503(
        self,
        service_mock: Mock,
    ) -> None:
        """Treat impossible accepted requests as deployment configuration errors."""
        self.client.force_login(self.user)
        exceptions = (
            LlmProviderConfigurationError("credencial privada"),
            LlmQuotaReservationTooLarge("cuota privada"),
            InterpretationConfigurationError("caché privada"),
        )

        for index, exception in enumerate(exceptions):
            with self.subTest(exception=type(exception).__name__):
                service_mock.side_effect = exception
                response = self.client.post(
                    self.url,
                    data={
                        **self.valid_request,
                        "target_message": f"Mensaje de configuración {index}",
                    },
                    format="json",
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )
                self.assertEqual(
                    response.data["error"],
                    "interpretation_not_configured",
                )
                self.assertNotIn("privada", str(response.data))
                self.assertNotIn("Retry-After", response)

        self.assertFalse(SecurityEvent.objects.exists())

    @patch("backend.interpretation.views.interpret_message")
    def test_local_rate_limit_returns_retry_after_and_deduplicates_audit(
        self,
        service_mock: Mock,
    ) -> None:
        """Persist only one rate event for repeated rejects in one reset window."""
        service_mock.side_effect = LlmRateLimitExceeded(
            retry_after_seconds=17
        )
        self.client.force_login(self.user)

        responses = [
            self.client.post(
                self.url,
                data={
                    **self.valid_request,
                    "target_message": f"Mensaje limitado {index}",
                },
                format="json",
            )
            for index in range(2)
        ]

        for response in responses:
            self.assertEqual(
                response.status_code,
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
            self.assertEqual(response["Retry-After"], "17")
            self.assertEqual(response.data["error"], "interpretation_rate_limited")

        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.RATE_LIMITED,
                actor=self.user,
            ).count(),
            1,
        )

    @patch("backend.interpretation.views.interpret_message")
    def test_duplicate_request_is_not_persisted_as_a_security_event(
        self,
        service_mock: Mock,
    ) -> None:
        """Treat ordinary repeat submission as a stable application conflict."""
        service_mock.side_effect = DuplicateInterpretationRequest(
            "huella privada"
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error"], "duplicate_interpretation_request")
        self.assertNotIn("huella privada", str(response.data))
        self.assertFalse(SecurityEvent.objects.exists())

    @patch("backend.interpretation.views.interpret_message")
    def test_post_enforces_csrf_before_external_processing(
        self,
        service_mock: Mock,
    ) -> None:
        """Require CSRF protection and keep its handled rejection non-cacheable."""
        service_mock.return_value = valid_service_result()
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_client.get(reverse("session-status"))
        csrf_token = csrf_client.cookies["csrftoken"].value

        rejected = csrf_client.post(
            self.url,
            data=self.valid_request,
            format="json",
        )
        accepted = csrf_client.post(
            self.url,
            data=self.valid_request,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(rejected.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(rejected.data["error"], "permission_denied")
        self.assert_private_no_store(rejected)
        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        service_mock.assert_called_once()
