"""Tests for minimized, append-only security audit events."""

import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser # Unauthenticated users.
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.test import RequestFactory, TestCase # RequestFactory is used to simulate HTTP requests in tests.

from backend.accounts.models import CustomUser

from .admin import SecurityEventAdmin
from .models import SecurityEvent, pseudonymize_ip_address, SecurityEventType


class SecurityEventModelTests(TestCase):
    """Verify audit events remain structured, attributed and immutable."""

    def test_pseudonymize_ip_address_is_keyed_and_deterministic(self) -> None:
        """Create a stable keyed digest without storing the raw IP address.

        Args:
            self: The test case instance.
        """
        first_digest = pseudonymize_ip_address("203.0.113.10", key=b"test-key") # Use b"test-key" to convert the string to a bytes object.
        second_digest = pseudonymize_ip_address("203.0.113.10", key=b"test-key")
        other_digest = pseudonymize_ip_address("203.0.113.10", key=b"other-key")

        self.assertEqual(first_digest, second_digest)
        self.assertNotEqual(first_digest, other_digest)
        self.assertEqual(len(first_digest), 64)
        self.assertNotEqual(first_digest, "203.0.113.10")

    def test_pseudonymize_ip_address_rejects_empty_key(self) -> None:
        """Reject pseudonymization without a secret key.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(ValueError):
            pseudonymize_ip_address("203.0.113.10", key=b"")

    def test_record_creates_event_with_request_id(self) -> None:
        """Persist an event with a generated request correlation ID.

        Args:
            self: The test case instance.
        """
        request_id = uuid.uuid4()

        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=request_id,
        )

        self.assertEqual(event.request_id, request_id)
        self.assertIsNone(event.actor_id_snapshot)
        self.assertEqual(event.event_type, SecurityEventType.LOGIN_FAILED)

    def test_record_captures_actor_snapshot(self) -> None:
        """Copy the local actor UUID at insert time for later traceability.

        Args:
            self: The test case instance.
        """
        actor = CustomUser.objects.create_user(
            google_subject="audit-actor-subject",
        )

        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_SUCCEEDED,
            actor=actor,
        )

        self.assertEqual(event.actor, actor)
        self.assertEqual(event.actor_id_snapshot, actor.id)

    def test_event_requires_minimum_attribution(self) -> None:
        """Reject events that cannot be correlated to actor, request or source.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILED,
        )

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_event_rejects_invalid_type_and_source_hash(self) -> None:
        """Reject free-form event names and malformed source IP hashes.

        Args:
            self: The test case instance.
        """
        invalid_type_event = SecurityEvent(
            event_type="message_body_logged",
            request_id=uuid.uuid4(),
        )
        invalid_hash_event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILED,
            source_ip_hash="raw-ip-address",
        )

        with self.assertRaises(ValidationError):
            invalid_type_event.full_clean()

        with self.assertRaises(ValidationError):
            invalid_hash_event.full_clean()

    def test_append_only_blocks_instance_update_and_delete(self) -> None:
        """Reject instance mutation after the initial audit insert.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )
        event.event_type = SecurityEventType.LOGOUT

        with self.assertRaises(ValidationError):
            event.save()

        with self.assertRaises(ValidationError):
            event.delete()

    def test_append_only_blocks_bulk_update_and_delete(self) -> None:
        """Reject queryset mutation APIs that bypass model save hooks.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )

        with self.assertRaises(ValidationError):
            SecurityEvent.objects.filter(pk=event.pk).update(
                event_type=SecurityEventType.LOGOUT,
            )

        with self.assertRaises(ValidationError):
            SecurityEvent.objects.filter(pk=event.pk).delete()

    def test_str_is_single_line_and_minimal(self) -> None:
        """Return a representation without control characters or raw content.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )

        rendered = str(event)

        self.assertNotIn("\n", rendered)
        self.assertNotIn("\r", rendered)
        self.assertIn(SecurityEventType.LOGIN_FAILED, rendered)

    def test_event_type_has_database_check_constraint(self) -> None:
        """Expose a database CHECK constraint for the event type list.

        Args:
            self: The test case instance.
        """
        constraint_names = {
            constraint.name
            for constraint in SecurityEvent._meta.constraints
        }

        self.assertIn("audit_event_type_valid", constraint_names)


class SecurityEventAdminTests(TestCase):
    """Verify audit administration is read-only and superuser-only."""

    def setUp(self) -> None:
        """Create request factory and admin instance for permission checks.

        Args:
            self: The test case instance.
        """
        self.factory = RequestFactory()
        self.model_admin = SecurityEventAdmin(SecurityEvent, admin.site)

    def _request_for(self, user: CustomUser | AnonymousUser) -> HttpRequest:
        """Build an admin request carrying the supplied user.

        Args:
            user: The authenticated or anonymous user attached to the request.

        Returns:
            A request object suitable for ModelAdmin permission checks.
        """
        request = self.factory.get("/admin/audit/securityevent/")
        request.user = user
        return request

    def test_audit_admin_denies_anonymous_and_staff_non_superuser_access(self) -> None:
        """Restrict audit inspection to active staff superusers.

        Args:
            self: The test case instance.
        """
        anonymous_request = self._request_for(AnonymousUser())
        staff_user = CustomUser.objects.create_staff_user(
            google_subject="audit-staff-subject",
        )
        staff_request = self._request_for(staff_user)

        self.assertFalse(self.model_admin.has_module_permission(anonymous_request))
        self.assertFalse(self.model_admin.has_view_permission(staff_request))

    def test_audit_admin_is_readonly_for_active_superuser(self) -> None:
        """Allow superuser inspection while blocking mutation in admin.

        Args:
            self: The test case instance.
        """
        superuser = CustomUser.objects.create_superuser(
            google_subject="audit-admin-subject",
        )
        request = self._request_for(superuser)

        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))
        self.assertIn("actor_id_snapshot", self.model_admin.readonly_fields)