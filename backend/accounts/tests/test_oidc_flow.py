"""Tests for the backend-managed Google OpenID Connect login flow."""

import uuid
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.cache import cache, caches
# override_setings allows temporarily changing the value of one or more Django project settings during 
# the execution of a unit test, automatically restoring the original values ​​once the test is complete
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from google.auth.exceptions import TransportError

from ..models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType
from ..services import GoogleOIDCConfigurationError
from ..services.flow_state import _state_cache_key as state_cache_key_for_testing
from .helpers import fake_jwt, valid_claims


@override_settings(
    DEBUG=True,
    GOOGLE_OIDC_CLIENT_ID="client-id.apps.googleusercontent.com",
    GOOGLE_OIDC_CLIENT_SECRET="test-client-secret",
    GOOGLE_OIDC_REDIRECT_URI="http://testserver/api/auth/google/callback/",
    GOOGLE_OIDC_AUTH_FLOW_TTL_SECONDS=300,
)
class GoogleOIDCFlowTests(TestCase):
    """Verify the backend-managed Google OAuth/OIDC login flow."""

    def setUp(self) -> None:
        """Clear temporary OAuth/OIDC state before each flow test.

        Args:
            self: The test case instance.
        """
        cache.clear()

    def _start_flow(self) -> tuple[str, dict[str, object], str]:
        """Start the Google login flow and return state metadata.

        Args:
            self: The test case instance.

        Returns:
            A tuple containing state, cache metadata and the cache key.
        """
        response = self.client.get(reverse("google-login-start"))

        # The expected code is 302 because the view must redirect.
        self.assertEqual(response.status_code, 302)
        # Gets the URL to which it redirects
        location = response["Location"]
        parsed_location = urlparse(location)
        # Converts the query string in a dictionary.
        query = parse_qs(parsed_location.query)
        state = query["state"][0]
        cache_key = state_cache_key_for_testing(state)
        metadata = cache.get(cache_key)

        # Verifies that the redirection goes to the correct endpoint, ignoring the parameters, like client_id.
        self.assertEqual(
            parsed_location.geturl().split("?", maxsplit=1)[0],
            "https://accounts.google.com/o/oauth2/v2/auth",
        )
        self.assertEqual(query["scope"], ["openid"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("code_challenge", query)
        self.assertIn("nonce", query)
        # client_secret should not be included in the URL.
        self.assertNotIn("client_secret", query)
        self.assertNotIn("code_verifier", query)
        self.assertIsInstance(metadata, dict)

        return state, metadata, cache_key

    def _complete_flow(
        self,
        *,
        state: str,
        metadata: dict[str, object],
        subject: str = "google-subject-flow",
        claims: dict[str, object] | None = None,
        id_token: str | None = None,
    ) -> object:
        """Complete a mocked Google callback.

        Args:
            self: The test case instance.
            state: The state value returned by _start_flow.
            metadata: The temporary flow metadata returned by _start_flow.
            subject: The Google OIDC subject to use when claims are generated.
            claims: Optional custom claims returned by the verifier mock.
            id_token: Optional fake JWT returned by the token exchange mock.

        Returns:
            The Django test client response.
        """
        nonce = str(metadata["nonce"])
        returned_claims = claims or valid_claims(
            nonce=nonce,
            subject=subject,
        )
        returned_id_token = id_token or fake_jwt()

        with (
            # Is used to customizes the behaviour of the real methods for the test.
            mock.patch(
                "backend.accounts.services.session.exchange_authorization_code_for_tokens",
                return_value={
                    "id_token": returned_id_token,
                    "access_token": "access-token-value",
                    "token_type": "Bearer",
                },
            ),
            mock.patch(
                "backend.accounts.services.token_validation.verify_google_id_token_signature",
                return_value=returned_claims,
            ),
        ):
            return self.client.get(
                reverse("google-login-callback"),
                {
                    "code": "authorization-code",
                    "state": state,
                },
            )

    def _assert_frontend_redirect(
        self,
        response: object,
        *,
        authentication_failed: bool,
    ) -> None:
        """Assert that a callback redirects to React without sensitive values.

        Args:
            self: The test case instance.
            response: The Django test client response to inspect.
            authentication_failed: Whether the redirect should carry the
            generic non-sensitive error fragment.
        """
        frontend_return_url = settings.FRONTEND_AUTH_RETURN_URL or "http://testserver/"
        expected_location = (
            f"{frontend_return_url}#auth-error"
            if authentication_failed
            else frontend_return_url
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], expected_location)
        self.assertNotIn("authorization-code", response["Location"])
        self.assertNotIn("access-token-value", response["Location"])
        self.assertNotIn("state", response["Location"])
        self.assertNotIn("code=", response["Location"])

    def test_start_creates_backend_only_temporary_flow_with_pkce(self) -> None:
        """Store nonce and PKCE verifier only in the backend temporary cache.

        Args:
            self: The test case instance.
        """
        state, metadata, _cache_key = self._start_flow()
        # Converts de dict in a string representation.
        session_values = repr(dict(self.client.session.items()))

        self.assertEqual(metadata["client_id"], "client-id.apps.googleusercontent.com")
        self.assertEqual(
            metadata["redirect_uri"],
            "http://testserver/api/auth/google/callback/",
        )
        self.assertEqual(metadata["code_challenge_method"], "S256")
        self.assertNotIn(str(metadata["nonce"]), session_values)
        self.assertNotIn(str(metadata["code_verifier"]), session_values)
        self.assertNotIn(state, session_values)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "google-oidc-default-test",
            },
            "oidc_flow": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "google-oidc-flow-test",
            },
        },
        GOOGLE_OIDC_FLOW_CACHE_ALIAS="oidc_flow",
        GOOGLE_OIDC_REQUIRE_SHARED_FLOW_CACHE=False,
    )
    def test_start_uses_configured_flow_cache_alias(self) -> None:
        """Store temporary OIDC metadata in the configured cache alias.

        Args:
            self: The test case instance.
        """
        caches["default"].clear()
        caches["oidc_flow"].clear()

        response = self.client.get(reverse("google-login-start"))

        self.assertEqual(response.status_code, 302)
        state = parse_qs(urlparse(response["Location"]).query)["state"][0]
        cache_key = state_cache_key_for_testing(state)

        self.assertIsNone(caches["default"].get(cache_key))
        self.assertIsInstance(caches["oidc_flow"].get(cache_key), dict)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "google-oidc-local-only-test",
            },
        },
        DEBUG=False,
        FRONTEND_AUTH_RETURN_URL="https://testserver/",
        GOOGLE_OIDC_REDIRECT_URI="https://testserver/api/auth/google/callback/",
        GOOGLE_OIDC_REQUIRE_SHARED_FLOW_CACHE=True,
    )
    def test_start_rejects_local_memory_cache_when_shared_cache_required(self) -> None:
        """Reject production OIDC startup with a per-process cache backend.

        Args:
            self: The test case instance.
        """
        response = self.client.get(reverse("google-login-start"))

        self._assert_frontend_redirect(response, authentication_failed=True)

    @override_settings(DEBUG=False, FRONTEND_AUTH_RETURN_URL="")
    def test_production_requires_explicit_frontend_return_url(self) -> None:
        """Reject an implicit same-origin return URL outside development.

        Args:
            self: The test case instance.
        """
        with mock.patch(
            "backend.accounts.views.create_google_authorization_url",
            side_effect=GoogleOIDCConfigurationError("synthetic configuration failure"),
        ):
            response = self.client.get(reverse("google-login-start"), secure=True)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "authentication_unavailable"})

    @override_settings(DEBUG=False)
    def test_frontend_return_url_rejects_embedded_credentials(self) -> None:
        """Reject configured return URLs containing user information.

        Args:
            self: The test case instance.
        """
        for return_url in (
            "https://user@testserver/",
            "https://user:password@testserver/",
        ):
            with self.subTest(return_url=return_url), self.settings(
                FRONTEND_AUTH_RETURN_URL=return_url,
            ), mock.patch(
                "backend.accounts.views.create_google_authorization_url",
                side_effect=GoogleOIDCConfigurationError(
                    "synthetic configuration failure"
                ),
            ):
                response = self.client.get(reverse("google-login-start"))

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json(),
                {"error": "authentication_unavailable"},
            )

    def test_callback_authenticates_new_user_rotates_session_and_consumes_flow(self) -> None:
        """Authenticate a new user only after state and ID token validation.

        Args:
            self: The test case instance.
        """
        state, metadata, cache_key = self._start_flow()
        # Stores the session key before the login.
        initial_session_key = self.client.session.session_key

        # Simulates the Google callback (the end of the flow).
        response = self._complete_flow(state=state, metadata=metadata)

        self._assert_frontend_redirect(response, authentication_failed=False)
        # Verifies that metadata was removed.
        self.assertIsNone(cache.get(cache_key))
        # Verifies the rotation of the session.
        self.assertNotEqual(initial_session_key, self.client.session.session_key)
        self.assertEqual(
            self.client.get(reverse("session-status")).json(),
            {"authenticated": True},
        )

        user = CustomUser.objects.get(google_subject="google-subject-flow")

        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIsNone(user.email)
        self.assertIsNone(user.first_name)
        self.assertIsNone(user.last_name)
        authentication_events = list(
            SecurityEvent.objects.filter(
                actor=user,
                event_type__in=(
                    SecurityEventType.ACCOUNT_CREATED,
                    SecurityEventType.LOGIN_SUCCEEDED,
                ),
            )
        )
        self.assertEqual(len(authentication_events), 2)
        request_ids = {event.request_id for event in authentication_events}
        self.assertEqual(len(request_ids), 1)
        self.assertIsInstance(request_ids.pop(), uuid.UUID)

        response_body = response.content.decode("utf-8")
        session_values = repr(dict(self.client.session.items()))

        for sensitive_value in (
            "authorization-code",
            "access-token-value",
            str(metadata["nonce"]),
            str(metadata["code_verifier"]),
            "google-subject-flow",
        ):
            # Ensures that sensitive data is not leaked in the HTTP response body, redirect URL and session.
            self.assertNotIn(sensitive_value, response_body)
            self.assertNotIn(sensitive_value, response["Location"])
            self.assertNotIn(sensitive_value, session_values)

    def test_callback_uses_existing_user_without_privilege_escalation(self) -> None:
        """Reuse an existing subject and keep normal permissions unchanged.

        Args:
            self: The test case instance.
        """
        existing_user = CustomUser.objects.create_user(
            google_subject="google-subject-existing",
        )
        state, metadata, _cache_key = self._start_flow()

        response = self._complete_flow(
            state=state,
            metadata=metadata,
            subject="google-subject-existing",
        )

        self._assert_frontend_redirect(response, authentication_failed=False)
        self.assertEqual(CustomUser.objects.count(), 1)
        existing_user.refresh_from_db()
        self.assertFalse(existing_user.is_staff)
        self.assertFalse(existing_user.is_superuser)

    def test_callback_rejects_missing_wrong_reused_and_expired_state(self) -> None:
        """Reject callbacks without a valid one-time state value.

        Args:
            self: The test case instance.
        """
        # Request to the callback without state.
        missing_response = self.client.get(
            reverse("google-login-callback"),
            {"code": "authorization-code"},
        )

        self._assert_frontend_redirect(missing_response, authentication_failed=True)

        # Using a wrong state.
        wrong_response = self.client.get(
            reverse("google-login-callback"),
            {
                "code": "authorization-code",
                "state": "wrong-state",
            },
        )

        self._assert_frontend_redirect(wrong_response, authentication_failed=True)

        state, metadata, _cache_key = self._start_flow()
        first_response = self._complete_flow(state=state, metadata=metadata)
        second_response = self._complete_flow(state=state, metadata=metadata)

        self._assert_frontend_redirect(first_response, authentication_failed=False)
        self._assert_frontend_redirect(second_response, authentication_failed=True)

        expired_state, expired_metadata, expired_cache_key = self._start_flow()
        expired_metadata["expires_at"] = int(timezone.now().timestamp()) - 1
        cache.set(expired_cache_key, expired_metadata, timeout=300)
        expired_response = self._complete_flow(
            state=expired_state,
            metadata=expired_metadata,
        )

        self._assert_frontend_redirect(expired_response, authentication_failed=True)
        self.assertIsNone(cache.get(expired_cache_key))

    def test_callback_rejects_wrong_nonce(self) -> None:
        """Reject callbacks without a valid one-time nonce value.
        
        Args:
            self: The test case instance.
        """
        state, metadata, _cache_key = self._start_flow()
        claims = valid_claims(
            nonce="wrong-nonce",
            subject="google-subject-flow",
        )

        response = self._complete_flow(
            state=state,
            metadata=metadata,
            claims=claims,
        )

        self._assert_frontend_redirect(response, authentication_failed=True)
        self.assertFalse(
            CustomUser.objects.filter(
                google_subject="google-subject-flow",
            ).exists()
        )

    def test_callback_rejects_provider_error_without_details(self) -> None:
        """Handle provider-declared errors without echoing callback parameters.

        Args:
            self: The test case instance.
        """
        state, _metadata, cache_key = self._start_flow()
        response = self.client.get(
            reverse("google-login-callback"),
            {
                "error": "access_denied",
                "state": state,
                "code": "authorization-code",
            },
        )
        response_body = response.content.decode("utf-8")

        self._assert_frontend_redirect(response, authentication_failed=True)
        self.assertNotIn("access_denied", response_body)
        self.assertNotIn(state, response_body)
        self.assertNotIn("authorization-code", response_body)
        self.assertNotIn("access_denied", response["Location"])
        self.assertNotIn(state, response["Location"])
        self.assertNotIn("authorization-code", response["Location"])
        self.assertIsNone(cache.get(cache_key))

    def test_callback_rejects_id_token_with_disallowed_algorithm(self) -> None:
        """Reject ID tokens whose JWT alg header is not allowed.

        Args:
            self: The test case instance.
        """
        state, _metadata, _cache_key = self._start_flow()

        with (
            mock.patch(
                "backend.accounts.services.session.exchange_authorization_code_for_tokens",
                return_value={
                    "id_token": fake_jwt(algorithm="HS256"),
                    "access_token": "access-token-value",
                    "token_type": "Bearer",
                },
            ),
            mock.patch(
                "backend.accounts.services.token_validation.verify_google_id_token_signature",
            ) as verifier_mock,
        ):
            response = self.client.get(
                reverse("google-login-callback"),
                {
                    "code": "authorization-code",
                    "state": state,
                },
            )

        self._assert_frontend_redirect(response, authentication_failed=True)
        # This confirms that the backend does not attempt to cryptographically verify a token whose alg has already been rejected by policy.
        verifier_mock.assert_not_called()
        self.assertFalse(CustomUser.objects.exists())

    def test_callback_hides_tokens_when_certificate_fetch_fails(self) -> None:
        """Return a generic redirect when Google signing keys are unavailable.

        Args:
            self: The test case instance.
        """
        state, _metadata, _cache_key = self._start_flow()
        authorization_code = "sensitive-authorization-code"
        access_token = "sensitive-access-token"
        id_token = fake_jwt()
        provider_detail = "private-certificate-endpoint"

        with (
            mock.patch(
                "backend.accounts.services.session.exchange_authorization_code_for_tokens",
                return_value={
                    "id_token": id_token,
                    "access_token": access_token,
                    "token_type": "Bearer",
                },
            ),
            mock.patch(
                "google.oauth2.id_token.verify_oauth2_token",
                side_effect=TransportError(provider_detail),
            ),
        ):
            response = self.client.get(
                reverse("google-login-callback"),
                {
                    "code": authorization_code,
                    "state": state,
                },
            )

        self._assert_frontend_redirect(response, authentication_failed=True)
        public_response = response.content.decode("utf-8") + response["Location"]
        for sensitive_value in (
            authorization_code,
            state,
            access_token,
            id_token,
            provider_detail,
        ):
            with self.subTest(sensitive_value=sensitive_value):
                self.assertNotIn(sensitive_value, public_response)

        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.LOGIN_FAILED,
            ).exists()
        )


    def test_session_status_is_minimized(self) -> None:
        """Return only authentication status and no identifiers.

        Args:
            self: The test case instance.
        """
        anonymous_response = self.client.get(reverse("session-status"))

        self.assertEqual(anonymous_response.json(), {"authenticated": False})
        self.assertEqual(settings.CSRF_COOKIE_NAME, "csrftoken")
        self.assertFalse(settings.CSRF_COOKIE_HTTPONLY)
        self.assertFalse(settings.CSRF_USE_SESSIONS)
        self.assertIn(settings.CSRF_COOKIE_NAME, anonymous_response.cookies)
        self.assertFalse(
            anonymous_response.cookies[settings.CSRF_COOKIE_NAME]["httponly"]
        )

        user = CustomUser.objects.create_user(
            google_subject="google-subject-status",
        )
        self.client.force_login(user)
        authenticated_response = self.client.get(reverse("session-status"))

        self.assertEqual(authenticated_response.json(), {"authenticated": True})
        # to verify that the dictionary contains only that key.
        self.assertEqual(set(authenticated_response.json()), {"authenticated"})

    def test_logout_requires_session_and_clears_authenticated_session(self) -> None:
        """Require CSRF before logout and clear only an accepted session.

        Args:
            self: The test case instance.
        """
        anonymous_response = self.client.post(reverse("auth-logout"))

        self.assertEqual(anonymous_response.status_code, 403)

        user = CustomUser.objects.create_user(
            google_subject="google-subject-logout",
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        csrf_response = csrf_client.get(reverse("session-status"))
        csrf_token = csrf_response.cookies[settings.CSRF_COOKIE_NAME].value

        rejected_response = csrf_client.post(
            reverse("auth-logout"),
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(rejected_response.status_code, 403)
        self.assertIn("_auth_user_id", csrf_client.session)
        self.assertFalse(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.LOGOUT,
            ).exists()
        )

        accepted_response = csrf_client.post(
            reverse("auth-logout"),
            data="{}",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(accepted_response.status_code, 200)
        self.assertEqual(accepted_response.json(), {"authenticated": False})
        self.assertIn("no-store", accepted_response["Cache-Control"])
        self.assertNotIn("_auth_user_id", csrf_client.session)
        logout_event = SecurityEvent.objects.get(
            actor=user,
            event_type=SecurityEventType.LOGOUT,
        )
        self.assertIsInstance(logout_event.request_id, uuid.UUID)
