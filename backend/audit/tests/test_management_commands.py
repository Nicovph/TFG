"""Tests for controlled security audit maintenance commands."""

import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command, CommandError
from django.db import models
from django.test import TestCase
from django.utils import timezone

from ..models import SecurityEvent, SecurityEventType


class DeleteSecurityEventsCommandTests(TestCase):
    """Verify counting, confirmation, and deletion of audit events."""

    def _create_event(self) -> SecurityEvent:
        """Create one minimal synthetic security event.

        Returns:
            The newly persisted security event.
        """
        return SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )

    def _age_event(self, event: SecurityEvent, *, days: int) -> None:
        """Set a synthetic event age without weakening production safeguards.

        Args:
            event: Synthetic event to age for the command test.
            days: Number of days elapsed since the event occurred.
        """
        queryset = SecurityEvent.objects.filter(pk=event.pk)
        models.QuerySet.update(
            queryset,
            occurred_at=timezone.now() - timedelta(days=days),
        )

    # Patch builtins.input so the command receives a non-confirming response
    # ("cancelar") and takes the cancellation branch without blocking on real stdin.
    @patch("builtins.input", return_value="cancelar")
    def test_command_reports_count_and_requires_exact_confirmation(
        self,
        input_mock: Mock,
    ) -> None:
        """Preserve every event when the operator does not confirm exactly.

        Args:
            input_mock: Patched interactive input used by the command.
        """
        self._age_event(self._create_event(), days=2)
        self._age_event(self._create_event(), days=2)
        output = StringIO()

        call_command(
            "delete_security_events",
            older_than_days=1,
            stdout=output,
        )

        self.assertEqual(SecurityEvent.objects.count(), 2)
        self.assertIn(
            "Eventos de seguridad que se eliminarán: 2.",
            output.getvalue(),
        )
        self.assertIn("Operación cancelada", output.getvalue())
        self.assertEqual(input_mock.call_count, 1)

    @patch("builtins.input", return_value="ELIMINAR")
    def test_command_deletes_reported_events_and_is_idempotent(
        self,
        input_mock: Mock,
    ) -> None:
        """Delete confirmed rows and make a repeated empty run harmless.

        Args:
            input_mock: Patched interactive input used by the command.
        """
        expired = self._create_event()
        current = self._create_event()
        self._age_event(expired, days=2)
        first_output = StringIO()
        second_output = StringIO()

        call_command(
            "delete_security_events",
            older_than_days=1,
            stdout=first_output,
        )
        call_command(
            "delete_security_events",
            older_than_days=1,
            stdout=second_output,
        )

        self.assertFalse(SecurityEvent.objects.filter(pk=expired.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(pk=current.pk).exists())
        self.assertIn(
            "Eventos de seguridad que se eliminarán: 1.",
            first_output.getvalue(),
        )
        self.assertIn(
            "Eventos de seguridad eliminados: 1.",
            first_output.getvalue(),
        )
        self.assertIn(
            "Eventos de seguridad que se eliminarán: 0.",
            second_output.getvalue(),
        )
        self.assertEqual(input_mock.call_count, 1)

    @patch("builtins.input")
    def test_command_rejects_a_non_positive_age(
        self,
        input_mock: Mock,
    ) -> None:
        """Reject an unsafe age before counting or requesting confirmation.

        Args:
            input_mock: Patched interactive input that must remain unused.
        """
        with self.assertRaisesMessage(
            CommandError,
            "La antigüedad debe ser un número entero mayor que cero.",
        ):
            call_command("delete_security_events", older_than_days=0)

        input_mock.assert_not_called()
