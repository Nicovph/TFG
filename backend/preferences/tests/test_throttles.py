"""Tests for authenticated preference-update throttling."""

from types import SimpleNamespace

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType

from ..models import Theme, UserPreferences
from ..throttles import (
    PreferenceUpdateBurstThrottle,
    PreferenceUpdateSustainedThrottle,
)


@override_settings(
    PREFERENCES_UPDATE_ATTEMPTS_PER_MINUTE=1,
    PREFERENCES_UPDATE_ATTEMPTS_PER_DAY=10,
)
class PreferenceUpdateThrottleTests(TestCase):
    """Verify PATCH-only limits and pseudonymous user separation."""

    client_class = APIClient

    def setUp(self) -> None:
        """Create one authenticated user with isolated throttle state.

        Args:
            self: The test case instance.
        """
        cache.clear()
        self.user = CustomUser.objects.create_user(
            google_subject="preferences-throttle-subject",
        )
        self.preferences = UserPreferences.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.url = reverse("user-preferences")

    def test_keys_hide_uuid_and_use_configured_windows(self) -> None:
        """Keep the UUID out of distinct burst and sustained cache keys.

        Args:
            self: The test case instance.
        """
        django_request = APIRequestFactory().patch(
            self.url,
            {"theme": Theme.DARK},
            format="json",
        )
        force_authenticate(django_request, user=self.user)
        request = Request(django_request)
        burst = PreferenceUpdateBurstThrottle()
        sustained = PreferenceUpdateSustainedThrottle()

        burst_key = burst.get_cache_key(request, APIView())
        sustained_key = sustained.get_cache_key(request, APIView())

        self.assertIsInstance(burst_key, str)
        self.assertIsInstance(sustained_key, str)
        self.assertNotIn(str(self.user.id), burst_key)
        self.assertNotIn(self.user.id.hex, burst_key)
        self.assertNotEqual(burst_key, sustained_key)
        self.assertEqual(burst.get_rate(), "1/minute")
        self.assertEqual(sustained.get_rate(), "10/day")

    def test_only_patch_requires_a_uuid_primary_key(self) -> None:
        """Ignore reads but reject updates with an invalid authenticated key.

        Args:
            self: The test case instance.
        """
        invalid_user = SimpleNamespace(pk=1)
        get_request = APIRequestFactory().get(self.url)
        patch_request = APIRequestFactory().patch(
            self.url,
            {"theme": Theme.DARK},
            format="json",
        )
        force_authenticate(get_request, user=invalid_user)
        force_authenticate(patch_request, user=invalid_user)
        throttle = PreferenceUpdateBurstThrottle()

        self.assertIsNone(throttle.get_subject(Request(get_request), APIView()))
        with self.assertRaisesRegex(
            RuntimeError,
            "requieren una clave primaria de usuario de tipo UUID.",
        ):
            throttle.get_subject(Request(patch_request), APIView())

    def test_get_does_not_consume_patch_budget(self) -> None:
        """Leave preference reads outside the write-specific rate budget.

        Args:
            self: The test case instance.
        """
        for _ in range(3):
            self.assertEqual(
                self.client.get(self.url).status_code,
                status.HTTP_200_OK,
            )

        response = self.client.patch(
            self.url,
            {"theme": Theme.DARK},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_excess_patch_does_not_write_or_record_audit_event(self) -> None:
        """Reject excess updates before persistence and audit recording.

        Args:
            self: The test case instance.
        """
        accepted_response = self.client.patch(
            self.url,
            {"theme": Theme.DARK},
            format="json",
        )
        rejected_response = self.client.patch(
            self.url,
            {"theme": Theme.LIGHT},
            format="json",
        )

        self.assertEqual(accepted_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            rejected_response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        self.assertIn("no-store", rejected_response["Cache-Control"])
        self.assertGreater(int(rejected_response["Retry-After"]), 0)
        self.preferences.refresh_from_db()
        self.assertEqual(self.preferences.theme, Theme.DARK)
        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
                actor=self.user,
            ).count(),
            1,
        )
