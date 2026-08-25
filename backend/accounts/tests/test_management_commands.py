"""Tests for backend-only account management commands."""

from io import StringIO
from sys import stdout

from django.core.management.base import CommandError
from django.core.management import call_command
from django.test import TestCase

from backend.audit.models import SecurityEvent, SecurityEventType

from ..models import CustomUser


class PromoteUserCommandTests(TestCase):
    """Verify backend-only promotion for Django admin access."""

    def test_promote_user_command_grants_admin_flags_without_password(self) -> None:
        """Promote an existing user using the management command only.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="google-subject-promote",
        )
        output = StringIO() # It allows a text string to be treated as if it were a file.

        call_command(
            "promote_user",
            "--user-id",
            str(user.id),
            stdout=output,
        )

        # Django model method that reloads the object's data from the database, updating its current state with the latest information.
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        # getvalue() returns all the content that has been written to the StringIO since it was created.
        self.assertIn("Cuenta promovida", output.getvalue())
       # Compare if it was registered an unique security event of update for the user.
        self.assertEqual(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.ACCOUNT_SECURITY_UPDATED,
            ).count(),
            1,
        )

    def test_promote_user_command_accepts_google_subject_selector(self) -> None:
        """Promote an account selected by its opaque Google subject.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_user(
            google_subject="google-subject-selector",
        )

        output = StringIO()

        call_command(
            "promote_user",
            "--google-subject",
            "google-subject-selector",
            stdout=output,
        )

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertIn("Cuenta promovida", output.getvalue())

    def test_promote_user_command_rejects_invalid_uuid(self) -> None:
        """Reject malformed local UUID selectors before querying users.

        Args:
            self: The test case instance.
        """
        with self.assertRaisesMessage(CommandError, "El UUID de usuario no es válido."):
            call_command(
                "promote_user",
                "--user-id",
                "not-a-valid-uuid",
            )

    def test_promote_user_command_skips_already_promoted_user(self) -> None:
        """Avoid duplicate audit events when the user is already promoted.

        Args:
            self: The test case instance.
        """
        user = CustomUser.objects.create_superuser(
            google_subject="google-subject-already-promoted",
        )
        output = StringIO()

        call_command(
            "promote_user",
            "--user-id",
            str(user.id),
            stdout=output,
        )

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertIn("ya está promovida", output.getvalue())
        self.assertFalse(
            SecurityEvent.objects.filter(
                actor=user,
                event_type=SecurityEventType.ACCOUNT_SECURITY_UPDATED,
            ).exists()
        )
