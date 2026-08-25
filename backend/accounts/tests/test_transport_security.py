"""Tests for browser cookie and reverse-proxy transport security."""

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import CustomUser


@override_settings(
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    CSRF_COOKIE_SECURE=True,
    CSRF_COOKIE_SAMESITE="Lax",
)
class BrowserTransportSecurityTests(TestCase):
    """Verify the browser-facing HTTPS and cookie policy as one contract."""

    def test_https_proxy_sets_hardened_cookies_and_no_store(self) -> None:
        """Recognize proxy HTTPS and emit protected session and CSRF cookies.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="transport-security-subject",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("session-status"),
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertTrue(response.wsgi_request.is_secure())
        self.assertIn("no-store", response["Cache-Control"])

        session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session_cookie["secure"])
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")

        csrf_cookie = response.cookies[settings.CSRF_COOKIE_NAME]
        self.assertTrue(csrf_cookie["secure"])
        self.assertEqual(csrf_cookie["samesite"], "Lax")
