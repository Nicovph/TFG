"""Tests for user-owned preference persistence rules."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from backend.accounts.models import CustomUser

from .models import UserPreferences, Theme, InterpretationDetail


class UserPreferencesModelTests(TestCase):
    """Verify preference values are minimal, owned and constrained."""

    def test_preferences_defaults_are_minimal_and_user_owned(self) -> None:
        """Create default preferences for exactly one authenticated user.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-1",
        )

        preferences = UserPreferences.objects.create(user=user)

        self.assertEqual(preferences.user, user)
        self.assertTrue(preferences.visual_support_enabled)
        self.assertFalse(preferences.show_offensive_language)
        self.assertTrue(preferences.show_content_warnings)
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertEqual(
            preferences.interpretation_detail,
            InterpretationDetail.STANDARD,
        )

    def test_preferences_reject_invalid_choice_values(self) -> None:
        """Reject values outside backend-controlled preference enumerations.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-2",
        )
        preferences = UserPreferences(
            user=user,
            theme="unexpected-theme",
            interpretation_detail="unexpected-detail",
        )

        with self.assertRaises(ValidationError):
            preferences.full_clean()

    def test_preferences_are_unique_per_user(self) -> None:
        """Reject duplicate preference rows for the same local user.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-3",
        )
        UserPreferences.objects.create(user=user)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserPreferences.objects.create(user=user)

    def test_preference_choices_have_database_check_constraints(self) -> None:
        """Expose database CHECK constraints for preference enumerations.

        Args:
            self: The test case instance.
        """
        constraint_names = {
            constraint.name
            for constraint in UserPreferences._meta.constraints
        }
        # Verify that exists two check constraints in the database with the expected names.
        self.assertIn("preferences_theme_valid", constraint_names)
        self.assertIn("preferences_interpretation_detail_valid", constraint_names)

    def test_string_representation_uses_only_local_user_id(self) -> None:
        """Render the local user UUID without loading external profile data.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-4",
        )
        preferences = UserPreferences.objects.create(user=user)

        self.assertEqual(
            str(preferences),
            f"Preferencias de {user.id}",
        )