"""Tests for transactional user preference services."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType

from ..models import Theme, UserPreferences
from ..services import get_user_preferences, update_user_preferences


class UserPreferencesServiceTests(TestCase):
    """Verify the domain service remains safe if called outside the API view."""

    def test_update_service_distinguishes_empty_and_unknown_change_sets(self) -> None:
        """Distinguish invalid internal calls without echoing field names.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-subject",
        )

        with self.assertRaises(ValueError) as empty_error:
            update_user_preferences(user=user, changes={})

        # Expected error message defined in the service.
        self.assertEqual(
            str(empty_error.exception),
            "El conjunto de cambios de preferencias no puede estar vacío.",
        )

        with self.assertRaises(ValueError) as unknown_error:
            update_user_preferences(
                user=user,
                changes={"user_id": str(user.id)},
            )

        self.assertEqual(
            str(unknown_error.exception),
            "El conjunto de cambios de preferencias contiene campos no permitidos.",
        )
        self.assertNotIn("user_id", str(unknown_error.exception))

        self.assertFalse(UserPreferences.objects.filter(user=user).exists())
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_services_reject_missing_preference_state(self) -> None:
        """Expose a violated provisioning invariant instead of repairing it.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-missing-subject",
        )

        # The user has not preferences because of a provisioning violation.
        with self.assertRaises(UserPreferences.DoesNotExist):
            get_user_preferences(user=user)

        with self.assertRaises(UserPreferences.DoesNotExist):
            update_user_preferences(
                user=user,
                changes={"theme": Theme.DARK},
            )

        self.assertFalse(
            UserPreferences.objects.filter(user=user).exists(),
        )
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_update_service_ignores_changes_equal_to_persisted_values(self) -> None:
        """Preserve timestamps and audit history for an idempotent update.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-noop-subject",
        )
        preferences = UserPreferences.objects.create(
            user=user,
            theme=Theme.DARK,
        )
        original_updated_at = preferences.updated_at
        preference_table = UserPreferences._meta.db_table.upper()

        with CaptureQueriesContext(connection) as captured_queries:
            returned_preferences = update_user_preferences(
                user=user,
                changes={"theme": Theme.DARK},
            )

        preferences.refresh_from_db()
        # Comparing the PK is an explicit and reliable way to ensure
        # that the record was neither created nor replaced.
        self.assertEqual(returned_preferences.pk, preferences.pk)
        self.assertEqual(preferences.updated_at, original_updated_at)
        preference_update_queries = [
            query["sql"]
            for query in captured_queries.captured_queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
            and preference_table in query["sql"].upper()
        ]
        self.assertEqual(preference_update_queries, [])
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_update_service_applies_mixed_changes_and_records_one_event(
        self,
    ) -> None:
        """Apply a mixed change set and audit one effective modification.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-effective-subject",
        )
        preferences = UserPreferences.objects.create(user=user)

        returned_preferences = update_user_preferences(
            user=user,
            changes={
                "theme": Theme.SYSTEM,
                "visual_support_enabled": False,
            },
        )

        preferences.refresh_from_db()
        self.assertEqual(returned_preferences.pk, preferences.pk)
        self.assertFalse(returned_preferences.visual_support_enabled)
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertFalse(preferences.visual_support_enabled)
        self.assertEqual(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).count(),
            1,
        )

    def test_update_service_rejects_invalid_allowed_values(self) -> None:
        """Validate allowed fields again when the API serializer is bypassed.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-invalid-value-subject",
        )
        preferences = UserPreferences.objects.create(user=user)
        original_updated_at = preferences.updated_at

        with self.assertRaises(ValidationError) as raised:
            update_user_preferences(
                user=user,
                changes={"theme": "invalid-theme"},
            )

        self.assertIn("theme", raised.exception.message_dict)
        preferences.refresh_from_db()
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertEqual(preferences.updated_at, original_updated_at)
        self.assertFalse(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_update_service_rolls_back_when_audit_recording_fails(self) -> None:
        """Roll back preference changes if their audit event cannot be stored.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="preferences-service-rollback-subject",
        )
        preferences = UserPreferences.objects.create(user=user)
        original_updated_at = preferences.updated_at

        with patch(
            "backend.preferences.services.SecurityEvent.objects.record",
            side_effect=RuntimeError("audit failure"),
        ) as record_event:
            with self.assertRaises(RuntimeError) as audit_error:
                update_user_preferences(
                    user=user,
                    changes={"theme": Theme.DARK},
                )

        self.assertEqual(str(audit_error.exception), "audit failure")
        # assert_called_once_with is used to verify that the mocked 
        # function was invoked exactly once with specific arguments.
        record_event.assert_called_once_with(
            event_type=SecurityEventType.PREFERENCES_UPDATED,
            actor=user,
        )
        preferences.refresh_from_db()
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertEqual(preferences.updated_at, original_updated_at)
        self.assertFalse(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )
