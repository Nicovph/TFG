"""Tests for user-owned preference persistence rules."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from backend.accounts.models import CustomUser

from ..models import InterpretationDetail, Theme, UserPreferences


class UserPreferencesModelTests(TestCase):
    """Verify preference defaults, ownership and persistence constraints."""

    def test_preferences_defaults_are_minimal_and_user_owned(self) -> None:
        """Create default preferences owned by one local user.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-1",
        )

        preferences = UserPreferences.objects.create(user=user)

        self.assertEqual(preferences.user, user)
        self.assertEqual(user.preferences, preferences)
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
            interpretation_detail="invalid-detail",
        )

        with self.assertRaises(ValidationError) as raised:
            preferences.full_clean()

        # Check both fields so one validation failure cannot hide another regression.
        # The "theme" key must appear in ValidationError message_dict.
        self.assertIn("theme", raised.exception.message_dict)
        self.assertIn(
            "interpretation_detail",
            raised.exception.message_dict,
        )

    def test_database_rejects_invalid_preference_choices(self) -> None:
        """Enforce closed preference choices at the database boundary.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-db-constraints",
        )
        preferences = UserPreferences.objects.create(user=user)
        invalid_updates = (
            {"theme": "unexpected-theme"},
            {"interpretation_detail": "invalid-detail"},
        )

        # Try performing a direct .update() on the database with an invalid value.
        for invalid_update in invalid_updates:
            with self.subTest(invalid_update=invalid_update):
                with self.assertRaises(IntegrityError):
                    # Isolate the expected database error so the test can continue.
                    with transaction.atomic():
                        UserPreferences.objects.filter(
                            pk=preferences.pk,
                        ).update(**invalid_update)

                preferences.refresh_from_db()
                self.assertEqual(preferences.theme, Theme.SYSTEM)
                self.assertEqual(
                    preferences.interpretation_detail,
                    InterpretationDetail.STANDARD,
                )

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

    def test_model_declares_named_choice_constraints(self) -> None:
        """Declare stable names for both preference choice constraints.

        Args:
            self: The test case instance.
        """
        constraint_names = {
            constraint.name
            for constraint in UserPreferences._meta.constraints
        }

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
        created_preferences = UserPreferences.objects.create(user=user)
        preferences = UserPreferences.objects.get(pk=created_preferences.pk)

        with self.assertNumQueries(0):
            representation = str(preferences)

        self.assertEqual(
            representation,
            f"Preferencias de {user.id}",
        )

    def test_preferences_are_deleted_with_their_user(self) -> None:
        """Delete preference data when its owning user is deleted.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-subject-cascade",
        )
        preferences = UserPreferences.objects.create(user=user)
        preferences_id = preferences.pk

        user.delete()

        self.assertFalse(
            UserPreferences.objects.filter(
                pk=preferences_id,
            ).exists(),
        )
