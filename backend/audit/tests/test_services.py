"""Tests for failure-isolated and data-minimised security event recording."""

import uuid
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from backend.accounts.models import CustomUser

from ..models import SecurityEventType
from ..services import record_security_event_best_effort


class SecurityEventServiceTests(SimpleTestCase):
    """Verify audit failures never replace the application's primary result."""

    def setUp(self) -> None:
        """Create one synthetic actor without writing to the database.

        Args:
            self: The test case instance.
        """
        self.actor = Mock(spec=CustomUser)
        self.actor.id = uuid.uuid4()

    @patch("backend.audit.services.SecurityEvent.objects.record")
    def test_success_returns_true_and_uses_only_the_closed_interface(
        self,
        record_mock: Mock,
    ) -> None:
        """Delegate a valid event to the append-only manager.

        Args:
            record_mock: Mocked manager method used to avoid database writes.
        """
        recorded = record_security_event_best_effort(
            event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
            actor=self.actor,
        )

        self.assertTrue(recorded)
        record_mock.assert_called_once_with(
            event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
            actor=self.actor,
        )

    @patch("backend.audit.services.get_current_request_id")
    @patch("backend.audit.services.SecurityEvent.objects.record")
    def test_failure_returns_false_and_logs_no_sensitive_details(
        self,
        record_mock: Mock,
        request_id_mock: Mock,
    ) -> None:
        """Report a sanitized operational failure without propagating it.

        Args:
            record_mock: Mocked manager method configured to fail.
            request_id_mock: Mocked trusted request-correlation accessor.
        """
        request_id = uuid.uuid4()
        private_failure = "private-database-endpoint"
        request_id_mock.return_value = request_id
        record_mock.side_effect = RuntimeError(private_failure)

        with self.assertLogs("backend.audit.services", level="ERROR") as logs:
            recorded = record_security_event_best_effort(
                event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
                actor=self.actor,
            )

        rendered_logs = " ".join(logs.output)
        self.assertFalse(recorded)
        self.assertIn("outcome=error", rendered_logs)
        self.assertIn(
            f"event_type={SecurityEventType.LLM_OUTPUT_REJECTED}",
            rendered_logs,
        )
        self.assertIn(f"request_id={request_id}", rendered_logs)
        self.assertNotIn(str(self.actor.id), rendered_logs)
        self.assertNotIn(private_failure, rendered_logs)

    @patch("backend.audit.services.get_current_request_id")
    @patch("backend.audit.services.SecurityEvent.objects.record")
    def test_invalid_event_type_is_rejected_without_log_injection(
        self,
        record_mock: Mock,
        request_id_mock: Mock,
    ) -> None:
        """Reject non-enumerated categories without logging their raw value.

        Args:
            record_mock: Mocked manager method that must remain unused.
            request_id_mock: Mocked trusted request-correlation accessor.
        """
        request_id_mock.return_value = uuid.uuid4()
        injected_event_type = "forged\nsecurity-event"

        with self.assertLogs("backend.audit.services", level="ERROR") as logs:
            recorded = record_security_event_best_effort(
                event_type=injected_event_type,  # type: ignore[arg-type]
                actor=self.actor,
            )

        rendered_logs = " ".join(logs.output)
        self.assertFalse(recorded)
        record_mock.assert_not_called()
        self.assertIn("event_type=invalid", rendered_logs)
        self.assertNotIn(injected_event_type, rendered_logs)
