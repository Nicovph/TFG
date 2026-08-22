"""Tests for session-bound Google login-start throttling."""

from unittest import mock

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from backend.audit.models import SecurityEvent, SecurityEventType

from ..throttles import GoogleLoginStartSessionThrottle


@override_settings(
    FRONTEND_AUTH_RETURN_URL="https://frontend.example/",
    GOOGLE_OIDC_LOGIN_ATTEMPTS_PER_MINUTE=1,
)
class GoogleLoginStartThrottleTests(TestCase):
    """Verify login-flow limits without exposing the session identifier."""

    def setUp(self) -> None:
        """Clear transient counters before each independent scenario.

        Args:
            self: The test case instance.
        """
        cache.clear()
        self.url = reverse("google-login-start")

    def test_cache_key_is_hmac_of_server_created_session(self) -> None:
        """Create a session and keep its raw key out of the throttle cache key.

        Args:
            self: The test case instance.
        """
        django_request = APIRequestFactory().get(self.url)
        # # Attach a session to the request so the throttle can derive a stable cache key.
        SessionMiddleware(lambda request: None).process_request(django_request)
        request = Request(django_request)
        throttle = GoogleLoginStartSessionThrottle()

        cache_key = throttle.get_cache_key(request, APIView())
        session_key = request.session.session_key

        self.assertIsInstance(session_key, str)
        self.assertIsInstance(cache_key, str)
        self.assertNotIn(session_key, cache_key)
        self.assertEqual(throttle.get_rate(), "1/minute")

    def test_missing_key_after_session_creation_fails_closed(self) -> None:
        """Reject an invalid session backend result instead of using None.

        Args:
            self: The test case instance.
        """
        django_request = APIRequestFactory().get(self.url)
        SessionMiddleware(lambda request: None).process_request(django_request)
        request = Request(django_request)
        throttle = GoogleLoginStartSessionThrottle()

        # Force session.create() to do nothing so no session_key is generated.
        with mock.patch.object(request.session, "create") as create_session:
            with self.assertRaisesRegex(
                RuntimeError,
                "falló al crear una sesión del lado del servidor",
            ):
                throttle.get_subject(request, APIView())

        create_session.assert_called_once_with()

    def test_repeated_start_returns_to_frontend_without_creating_another_flow(self) -> None:
        """Redirect a throttled browser flow without invoking OIDC a second time.

        Args:
            self: The test case instance.
        """
        with mock.patch(
            "backend.accounts.views.create_google_authorization_url",
            return_value="https://accounts.google.com/o/oauth2/v2/auth",
        ) as create_flow:
            first_response = self.client.get(self.url)
            session_key = self.client.session.session_key
            rejected_response = self.client.get(self.url)

        # Successful start must redirect the client to Google's authorization endpoint.
        self.assertEqual(first_response.status_code, status.HTTP_302_FOUND)
        frontend_url = settings.FRONTEND_AUTH_RETURN_URL or "http://testserver/"
        # Rate-limited login must redirect to the frontend error fragment without following it.
        self.assertRedirects(
            rejected_response,
            f"{frontend_url}#auth-rate-limited",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.session.session_key, session_key)
        self.assertIn("no-store", rejected_response["Cache-Control"])
        self.assertNotIn("Retry-After", rejected_response)
        self.assertNotIn(session_key, rejected_response.content.decode("utf-8"))
        audit_event = SecurityEvent.objects.get(
            event_type=SecurityEventType.RATE_LIMITED,
        )
        self.assertIsNone(audit_event.actor)
        self.assertIsNotNone(audit_event.request_id)
        create_flow.assert_called_once()

    def test_audit_is_globally_deduplicated_across_sessions(self) -> None:
        """Persist one event when separate sessions are throttled together.

        Args:
            self: The test case instance.
        """
        other_client = Client()

        with mock.patch(
            "backend.accounts.views.create_google_authorization_url",
            return_value="https://accounts.google.com/o/oauth2/v2/auth",
        ):
            for client in (self.client, other_client):
                client.get(self.url)
                client.get(self.url)

        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.RATE_LIMITED,
            ).count(),
            1,
        )

    def test_audit_cache_failure_does_not_block_frontend_redirect(self) -> None:
        """Keep the rate-limit response usable when deduplication fails.

        Args:
            self: The test case instance.
        """
        with (
            mock.patch(
                "backend.accounts.views.create_google_authorization_url",
                return_value="https://accounts.google.com/o/oauth2/v2/auth",
            ),
            mock.patch(
                "backend.accounts.rate_limit_audit.cache.add",
                side_effect=RuntimeError("synthetic cache failure"),
            ),
            self.assertLogs("backend.accounts.rate_limit_audit", level="WARNING"),
        ):
            self.client.get(self.url)
            rejected_response = self.client.get(self.url)

        self.assertRedirects(
            rejected_response,
            f"{settings.FRONTEND_AUTH_RETURN_URL}#auth-rate-limited",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.RATE_LIMITED,
            ).exists()
        )

    @override_settings(FRONTEND_AUTH_RETURN_URL="https://frontend.example/#invalid")
    def test_invalid_frontend_url_preserves_safe_throttle_response(self) -> None:
        """Keep DRF's 429 response when the frontend redirect is misconfigured.

        Args:
            self: The test case instance.
        """
        with mock.patch(
            "backend.accounts.views.create_google_authorization_url",
            return_value="https://accounts.google.com/o/oauth2/v2/auth",
        ) as create_flow:
            self.client.get(self.url)
            rejected_response = self.client.get(self.url)

        self.assertEqual(
            rejected_response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        self.assertGreater(int(rejected_response["Retry-After"]), 0)
        self.assertIn("no-store", rejected_response["Cache-Control"])
        create_flow.assert_called_once()

    def test_different_sessions_have_independent_budgets(self) -> None:
        """Allow one login start for each independently issued session.

        Args:
            self: The test case instance.
        """
        other_client = Client()

        with mock.patch(
            "backend.accounts.views.create_google_authorization_url",
            return_value="https://accounts.google.com/o/oauth2/v2/auth",
        ) as create_flow:
            first_response = self.client.get(self.url)
            other_response = other_client.get(self.url)

        self.assertEqual(first_response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(other_response.status_code, status.HTTP_302_FOUND)
        self.assertNotEqual(
            self.client.session.session_key,
            other_client.session.session_key,
        )
        self.assertEqual(create_flow.call_count, 2)
