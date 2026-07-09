"""Tests for local account provisioning from validated Google OIDC claims."""

from django.test import TestCase

from backend.audit.models import SecurityEvent, SecurityEventType
from backend.preferences.models import (
    InterpretationDetail,
    Theme,
    UserPreferences,
)

from .. import services
from ..models import CustomUser


class GoogleOIDCProvisioningTests(TestCase):
    """Verify validated OIDC claims provision minimal local users."""

    def test_provision_user_from_claims_returns_result_for_new_user(self) -> None:
        """Return a named result when provisioning a new federated user.

        Args:
            self: The test case instance.
        """
        result = services.provision_user_from_claims(
            {"sub": "google-subject-provision-new"}
        )

        self.assertIsInstance(result, services.GoogleLoginResult)
        self.assertTrue(result.created)
        self.assertEqual(result.user.google_subject, "google-subject-provision-new")
        self.assertFalse(result.user.has_usable_password())

        preferences = UserPreferences.objects.get(user=result.user)
        self.assertTrue(preferences.visual_support_enabled)
        self.assertFalse(preferences.show_offensive_language)
        self.assertTrue(preferences.show_content_warnings)
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertEqual(
            preferences.interpretation_detail,
            InterpretationDetail.STANDARD,
        )

        self.assertEqual(
            SecurityEvent.objects.filter(
                actor=result.user,
                event_type=SecurityEventType.ACCOUNT_CREATED,
            ).count(),
            1,
        )

    def test_provision_user_from_claims_returns_result_for_existing_user(self) -> None:
        """Return a named result when reusing an existing federated user.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="google-subject-provision-existing",
        )

        result = services.provision_user_from_claims(
            {"sub": "google-subject-provision-existing"}
        )

        self.assertIsInstance(result, services.GoogleLoginResult)
        self.assertFalse(result.created)
        self.assertEqual(result.user, user)
        self.assertFalse(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.ACCOUNT_CREATED,
            ).exists()
        )

    def test_provision_user_from_claims_does_not_duplicate_existing_preferences(self) -> None:
        """Keep existing preferences unchanged when provisioning is repeated.

        Args:
            self: The test case instance.
        """
        first_result = services.provision_user_from_claims(
            {"sub": "google-subject-provision-duplicate-preferences"}
        )
        original_preferences = UserPreferences.objects.get(user=first_result.user)

        second_result = services.provision_user_from_claims(
            {"sub": "google-subject-provision-duplicate-preferences"}
        )

        self.assertFalse(second_result.created)
        self.assertEqual(second_result.user, first_result.user)
        self.assertEqual(
            UserPreferences.objects.filter(user=first_result.user).count(),
            1,
        )
        self.assertEqual(
            UserPreferences.objects.get(user=first_result.user),
            original_preferences,
        )
        self.assertEqual(
            SecurityEvent.objects.filter(
                actor=first_result.user,
                event_type=SecurityEventType.ACCOUNT_CREATED,
            ).count(),
            1,
        )

    def test_provision_user_from_claims_rejects_missing_subject(self) -> None:
        """Reject claims that do not contain an OIDC subject.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(services.GoogleOIDCTokenError):
            services.provision_user_from_claims({})

    def test_provision_user_from_claims_rejects_empty_subject(self) -> None:
        """Reject claims that contain an empty OIDC subject.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(services.GoogleOIDCTokenError):
            services.provision_user_from_claims({"sub": ""})

    def test_provision_user_from_claims_rejects_non_string_subject(self) -> None:
        """Reject claims that contain a non-string OIDC subject.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(services.GoogleOIDCTokenError):
            services.provision_user_from_claims({"sub": 12345})

    def test_provision_user_from_claims_rejects_invalid_subject_format(self) -> None:
        """Reject claims whose subject does not match the local validator.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(services.GoogleOIDCTokenError):
            services.provision_user_from_claims({"sub": "invalid subject"})
