"""Tests for the privacy-minimized federated account model."""

import uuid

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.test import TestCase

from ..models import CustomUser


class CustomUserModelTests(TestCase):
    """Verify the local account model preserves federated identity invariants."""

    def test_create_user_stores_minimal_federated_identity(self) -> None:
        """Create a user without local credentials or profile claims.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="google-subject-1",
        )

        self.assertIsInstance(user.id, uuid.UUID)
        self.assertEqual(user.google_subject, "google-subject-1")
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.check_password("any-password"))
        self.assertIsNone(user.email)
        self.assertIsNone(user.first_name)
        self.assertIsNone(user.last_name)
        self.assertEqual(user.get_full_name(), "")
        self.assertEqual(user.get_short_name(), "")

    def test_create_user_rejects_local_password(self) -> None:
        """Reject local password creation for a federated account.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(ValueError):
            CustomUser.objects.create_user(
                google_subject="google-subject-2",
                password="local-password",
            )

    def test_create_user_does_not_accept_privilege_escalation_fields(self) -> None:
        """Keep normal users unprivileged even if caller passes privilege flags.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="google-subject-3",
            is_staff=True,
            is_superuser=True,
        )

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_staff_user_sets_staff_without_superuser_privileges(self) -> None:
        """Create an explicit staff account without granting superuser privileges."""
        user = CustomUser.objects.create_staff_user(
            google_subject="google-subject-staff-creation",
        )

        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_save_rejects_usable_password_hash(self) -> None:
        """Reject manual insertion of a usable local password hash.

        Args:
            self: The test case instance.
        """
        user = CustomUser(
            google_subject="google-subject-4",
        )
        user.password = make_password("local-password")

        with self.assertRaises(ValidationError):
            user.save()

    def test_google_subject_rejects_control_characters(self) -> None:
        """Reject control characters in the opaque OIDC subject.

        Args:
            self: The test case instance.
        """
        user = CustomUser(
            google_subject="bad\nsubject",
        )
        user.set_unusable_password()

        with self.assertRaises(ValidationError):
            user.full_clean()
