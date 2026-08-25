"""Integration test for transient interpretation data across backend stores."""

import logging
from logging.handlers import BufferingHandler
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import caches
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent
from backend.preferences.models import UserPreferences

from ..contracts import LLMInterpretationOutput
from ..models import LLMRateLimitState
from .helpers import valid_output_payload


@override_settings(
    INTERPRETATION_HMAC_KEY="integration-privacy-test-key-with-at-least-32-bytes",
)
class InterpretationFlowPrivacyTests(TestCase):
    """Verify one accepted flow persists counters but no user message."""

    client_class = APIClient

    @patch("backend.interpretation.services.request_interpretation")
    def test_message_remains_outside_responses_logs_sessions_and_models(
        self,
        provider_mock: Mock,
    ) -> None:
        """Keep a unique input marker transient across the complete backend flow.

        Args:
            self: The test case instance.
            provider_mock: Synthetic provider boundary replacing external Groq.
        """
        marker = "PRIVACY_FLOW_MARKER_7F4C2A9E"
        user = CustomUser.objects.create_user(
            google_subject="integration-privacy-subject",
        )
        UserPreferences.objects.create(user=user)
        caches[settings.LLM_DUPLICATE_CACHE_ALIAS].clear()
        provider_mock.return_value = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )
        self.client.force_login(user)

        log_capture = BufferingHandler(capacity=100)
        interpretation_logger = logging.getLogger("backend.interpretation")
        interpretation_logger.addHandler(log_capture)
        try:
            response = self.client.post(
                reverse("api-interpretation"),
                {
                    "target_message": (
                        f"Si puedes, cierra la ventana. {marker}"
                    ),
                    "external_processing_acknowledged": True,
                },
                format="json",
            )
        finally:
            interpretation_logger.removeHandler(log_capture)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(marker, response.content.decode("utf-8"))
        self.assertNotIn(
            marker,
            " ".join(record.getMessage() for record in log_capture.buffer),
        )
        self.assertTrue(LLMRateLimitState.objects.exists())
        stored_values = repr(
            (
                list(SecurityEvent.objects.values()),
                list(LLMRateLimitState.objects.values()),
                list(UserPreferences.objects.values()),
                list(Session.objects.values()),
            )
        )
        self.assertNotIn(marker, stored_values)
        self.assertNotIn(marker, repr(dict(self.client.session.items())))
        provider_mock.assert_called_once()
