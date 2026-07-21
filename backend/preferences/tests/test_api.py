"""Tests for the authenticated user preferences API contract."""

import json
import uuid

from django.db import connection
from django.test import TestCase

# To capture (and count) the SQL queries executed during a block of code.
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType

from ..models import InterpretationDetail, Theme, UserPreferences


class UserPreferencesApiTests(TestCase):
    """Verify session ownership, strict validation, CSRF and minimisation."""

    client_class = APIClient

    def setUp(self) -> None:
        """Create two independent federated users for API isolation tests.

        Args:
            self: The test case instance.
        """
        self.user = CustomUser.objects.create_user(
            google_subject="preferences-api-subject-1",
        )
        self.other_user = CustomUser.objects.create_user(
            google_subject="preferences-api-subject-2",
        )
        self.url = reverse("user-preferences")

    def test_get_requires_authentication(self) -> None:
        """Reject preference disclosure without an authenticated session.

        Args:
            self: The test case instance.
        """
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_requires_authentication(self) -> None:
        """Reject preference updates without an authenticated session.

        Args:
            self: The test case instance.
        """
        response = self.client.patch(
            self.url,
            data={"theme": Theme.DARK},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            UserPreferences.objects.filter(user=self.user).exists(),
        )
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_get_returns_values_without_modifying_preferences(self) -> None:
        """Return existing values without modifying the preference record.

        Args:
            self: The test case instance.
        """
        UserPreferences.objects.create(user=self.user)
        self.client.force_login(self.user)

        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cache_directives = {
            directive.strip().lower()
            for directive in response["Cache-Control"].split(",")
        }
        self.assertIn("no-store", cache_directives)
        self.assertEqual(
            response.data,
            {
                "visual_support_enabled": True,
                "show_offensive_language": False,
                "show_content_warnings": True,
                "theme": Theme.SYSTEM,
                "interpretation_detail": InterpretationDetail.STANDARD,
            },
        )
        # Converts in a string with a valid JSON format.
        serialized_payload = json.dumps(response.data)
        self.assertNotIn(str(self.user.id), serialized_payload)
        self.assertNotIn("created_at", response.data)
        self.assertNotIn("updated_at", response.data)
        # Obtains the DB name.
        preference_table = UserPreferences._meta.db_table.upper()
        # Create a list of the write queries that affect the preferences table.
        preference_write_queries = [
            query["sql"]
            for query in captured_queries.captured_queries
            if query["sql"].lstrip().upper().startswith(
                ("INSERT", "UPDATE", "DELETE")
            )
            and preference_table in query["sql"].upper()
        ]
        self.assertEqual(preference_write_queries, [])
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_get_returns_only_authenticated_users_preferences(self) -> None:
        """Return the authenticated user's record instead of another user's.

        Args:
            self: The test case instance.
        """
        UserPreferences.objects.create(
            user=self.user,
            theme=Theme.DARK,
        )
        UserPreferences.objects.create(
            user=self.other_user,
            theme=Theme.LIGHT,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["theme"], Theme.DARK)

    def test_patch_updates_only_the_authenticated_users_preferences(self) -> None:
        """Derive ownership from the session and leave other users unchanged.

        Args:
            self: The test case instance.
        """
        own_preferences = UserPreferences.objects.create(user=self.user)
        other_preferences = UserPreferences.objects.create(user=self.other_user)
        self.client.force_login(self.user)

        response = self.client.patch(
            self.url,
            data={
                "theme": Theme.DARK,
                "visual_support_enabled": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cache_directives = {
            directive.strip().lower()
            for directive in response["Cache-Control"].split(",")
        }
        self.assertIn("no-store", cache_directives)
        # It reloads the model instance's field values from the database
        # to ensure the in-memory object reflects the current database state.
        own_preferences.refresh_from_db()
        other_preferences.refresh_from_db()
        self.assertEqual(own_preferences.theme, Theme.DARK)
        self.assertFalse(own_preferences.visual_support_enabled)
        self.assertFalse(own_preferences.show_offensive_language)
        self.assertTrue(own_preferences.show_content_warnings)
        self.assertEqual(
            own_preferences.interpretation_detail,
            InterpretationDetail.STANDARD,
        )
        self.assertEqual(other_preferences.theme, Theme.SYSTEM)
        self.assertTrue(other_preferences.visual_support_enabled)
        self.assertEqual(
            response.data,
            {
                "visual_support_enabled": False,
                "show_offensive_language": False,
                "show_content_warnings": True,
                "theme": Theme.DARK,
                "interpretation_detail": InterpretationDetail.STANDARD,
            },
        )

    def test_patch_records_single_structured_preference_update_event(self) -> None:
        """Record exactly one preference update event for the session user.

        Args:
            self: The test case instance.
        """
        UserPreferences.objects.create(user=self.user)
        self.client.force_login(self.user)
        client_supplied_request_id = uuid.uuid4()

        response = self.client.patch(
            self.url,
            data={"interpretation_detail": InterpretationDetail.DETAILED},
            format="json",
            HTTP_X_REQUEST_ID=str(client_supplied_request_id),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = SecurityEvent.objects.filter(
            event_type=SecurityEventType.PREFERENCES_UPDATED,
        )
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.actor, self.user)
        self.assertIsInstance(event.request_id, uuid.UUID)
        self.assertNotEqual(event.request_id, client_supplied_request_id)

    def test_patch_with_unchanged_values_does_not_write_or_record_event(
        self,
    ) -> None:
        """Avoid preference writes and audit events for an idempotent update.

        Args:
            self: The test case instance.
        """
        preferences = UserPreferences.objects.create(
            user=self.user,
            theme=Theme.SYSTEM,
        )
        original_updated_at = preferences.updated_at
        self.client.force_login(self.user)
        preference_table = UserPreferences._meta.db_table.upper()

        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.patch(
                self.url,
                data={"theme": Theme.SYSTEM},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        preferences.refresh_from_db()
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
                actor=self.user,
            ).exists(),
        )

    def test_patch_rejects_unknown_identity_and_invalid_values(self) -> None:
        """Reject client-supplied ownership and values outside closed choices.

        Args:
            self: The test case instance.
        """
        self.client.force_login(self.user)

        invalid_payloads = (
            (
                {"user_id": str(self.other_user.id), "theme": Theme.DARK},
                "user_id",
            ),
            ({"theme": "unexpected-theme"}, "theme"),
            ({"visual_support_enabled": "yes"}, "visual_support_enabled"),
            ({}, "non_field_errors"),
            (["theme", Theme.DARK], "non_field_errors"),
        )

        for payload, expected_error_key in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.patch(
                    self.url,
                    data=payload,
                    format="json",
                )

                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(expected_error_key, response.data)

        self.assertFalse(UserPreferences.objects.filter(user=self.user).exists())
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_patch_requires_json_and_rejects_unsupported_methods(self) -> None:
        """Accept only the documented JSON GET and PATCH surface.

        Args:
            self: The test case instance.
        """
        self.client.force_login(self.user)

        form_response = self.client.patch(
            self.url,
            data="theme=dark",
            content_type="application/x-www-form-urlencoded",
        )
        post_response = self.client.post(
            self.url,
            data={"theme": Theme.DARK},
            format="json",
        )

        self.assertEqual(
            form_response.status_code,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
        self.assertEqual(
            post_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertFalse(
            UserPreferences.objects.filter(user=self.user).exists(),
        )
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

    def test_patch_enforces_csrf_for_authenticated_browser_sessions(self) -> None:
        """Require Django's CSRF token for state-changing session requests.

        Args:
            self: The test case instance.
        """
        preferences = UserPreferences.objects.create(user=self.user)
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_response = csrf_client.get(reverse("session-status"))

        self.assertEqual(csrf_response.status_code, status.HTTP_200_OK)
        self.assertIn("csrftoken", csrf_client.cookies)
        csrf_token = csrf_client.cookies["csrftoken"].value

        rejected_response = csrf_client.patch(
            self.url,
            data={"theme": Theme.DARK},
            format="json",
        )

        self.assertEqual(rejected_response.status_code, status.HTTP_403_FORBIDDEN)
        preferences.refresh_from_db()
        self.assertEqual(preferences.theme, Theme.SYSTEM)
        self.assertFalse(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
            ).exists(),
        )

        accepted_response = csrf_client.patch(
            self.url,
            data={"theme": Theme.DARK},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(accepted_response.status_code, status.HTTP_200_OK)
        preferences.refresh_from_db()
        self.assertEqual(preferences.theme, Theme.DARK)
        self.assertEqual(
            SecurityEvent.objects.filter(
                event_type=SecurityEventType.PREFERENCES_UPDATED,
                actor=self.user,
            ).count(),
            1,
        )
