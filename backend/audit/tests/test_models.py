"""Tests for minimized, append-only security audit event models."""

import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from backend.accounts.models import CustomUser

from ..models import SecurityEvent, SecurityEventType, pseudonymize_ip_address


class SecurityEventModelTests(TestCase):
    """Verify audit events remain structured, attributed and immutable."""

    def test_pseudonymize_ip_address_is_keyed_and_deterministic(self) -> None:
        """Create a stable keyed digest without storing the raw IP address.

        Args:
            self: The test case instance.
        """
        # Use b"test-key" to convert the string to a bytes object.
        first_digest = pseudonymize_ip_address("203.0.113.10", key=b"test-key")
        second_digest = pseudonymize_ip_address("203.0.113.10", key=b"test-key")
        other_key_digest = pseudonymize_ip_address(
            "203.0.113.10",
            key=b"other-key",
        )
        other_address_digest = pseudonymize_ip_address(
            "203.0.113.11",
            key=b"test-key",
        )

        self.assertEqual(first_digest, second_digest)
        self.assertNotEqual(first_digest, other_key_digest)
        self.assertNotEqual(first_digest, other_address_digest)
        self.assertEqual(len(first_digest), 64)
        self.assertRegex(first_digest, r"\A[0-9a-f]{64}\Z")
        self.assertNotEqual(first_digest, "203.0.113.10")

    def test_pseudonymize_ip_address_rejects_empty_key(self) -> None:
        """Reject pseudonymization without a secret key.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(ValueError):
            pseudonymize_ip_address("203.0.113.10", key=b"")

    def test_pseudonymize_ip_address_rejects_invalid_address(self) -> None:
        """Reject input that is not a valid IPv4 or IPv6 address.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(ValueError):
            pseudonymize_ip_address("not-an-ip-address", key=b"test-key")

    def test_pseudonymize_ip_address_normalizes_ipv6(self) -> None:
        """Produce one digest for equivalent IPv6 text representations.

        Args:
            self: The test case instance.
        """
        expanded = pseudonymize_ip_address(
            "2001:0db8:0000:0000:0000:0000:0000:0001",
            key=b"test-key",
        )
        compressed = pseudonymize_ip_address(
            "2001:db8::1",
            key=b"test-key",
        )

        self.assertEqual(expanded, compressed)

    def test_record_preserves_explicit_request_id(self) -> None:
        """Persist the request correlation ID supplied to the manager.

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

    def test_record_rejects_event_without_attribution(self) -> None:
        """Apply attribution validation through the public recording API.

        Args:
            self: The test case instance.
        """
        with self.assertRaises(ValidationError):
            SecurityEvent.objects.record(
                event_type=SecurityEventType.LOGIN_FAILED,
            )

        self.assertFalse(SecurityEvent.objects.exists())

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
        # Verify that, in the absence of a request context, the event is correctly
        # created without a `request_id`, maintaining the model's semantics.
        self.assertIsNone(event.request_id)

        actor_id = actor.id
        event_id = event.id
        actor.delete()
        persisted_event = SecurityEvent.objects.get(pk=event_id)

        self.assertIsNone(persisted_event.actor)
        self.assertEqual(persisted_event.actor_id_snapshot, actor_id)

    def test_event_schema_contains_only_minimal_structured_fields(self) -> None:
        """Keep the persisted audit schema closed to arbitrary content.

        Args:
            self: The test case instance.
        """
        concrete_field_names = {
            field.name
            for field in SecurityEvent._meta.concrete_fields
        }

        self.assertEqual(
            concrete_field_names,
            {
                "actor",
                "actor_id_snapshot",
                "event_type",
                "id",
                "occurred_at",
                "request_id",
                "source_ip_hash",
            },
        )

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

    def test_event_rejects_invalid_type(self) -> None:
        """Reject event names outside the closed choice list.

        Args:
            self: The test case instance.
        """
        invalid_type_event = SecurityEvent(
            event_type="message_body_logged",
            request_id=uuid.uuid4(),
        )
        with self.assertRaises(ValidationError) as context:
            invalid_type_event.full_clean()

        self.assertIn("event_type", context.exception.message_dict)

    def test_event_rejects_invalid_source_hash(self) -> None:
        """Reject source identifiers outside the HMAC digest format.

        Args:
            self: The test case instance.
        """
        invalid_hash_event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILED,
            source_ip_hash="raw-ip-address",
        )

        with self.assertRaises(ValidationError) as context:
            invalid_hash_event.full_clean()

        self.assertIn("source_ip_hash", context.exception.message_dict)

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

        event.refresh_from_db()
        self.assertEqual(event.event_type, SecurityEventType.LOGIN_FAILED)

        with self.assertRaises(ValidationError):
            event.delete()

        self.assertTrue(SecurityEvent.objects.filter(pk=event.pk).exists())

    def test_append_only_blocks_queryset_update_and_delete(self) -> None:
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

        event.refresh_from_db()
        self.assertEqual(event.event_type, SecurityEventType.LOGIN_FAILED)

        with self.assertRaises(ValidationError):
            SecurityEvent.objects.filter(pk=event.pk).delete()

        self.assertTrue(SecurityEvent.objects.filter(pk=event.pk).exists())

    def test_append_only_blocks_bulk_update(self) -> None:
        """Reject bulk updates that bypass individual model save methods.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )
        event.event_type = SecurityEventType.LOGOUT

        with self.assertRaises(ValidationError):
            SecurityEvent.objects.bulk_update(
                [event],
                ["event_type"],
            )

        event.refresh_from_db()
        self.assertEqual(event.event_type, SecurityEventType.LOGIN_FAILED)

    def test_append_only_blocks_public_bulk_create(self) -> None:
        """Reject bulk insertion that skips validation and snapshot hooks.

        Args:
            self: The test case instance.
        """
        event = SecurityEvent(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )

        with self.assertRaises(ValidationError):
            SecurityEvent.objects.bulk_create([event])

        self.assertFalse(SecurityEvent.objects.filter(pk=event.pk).exists())

    def test_str_is_single_line_and_minimal(self) -> None:
        """Return a representation without control characters or raw content.

        Args:
            self: The test case instance.
        """
        actor = CustomUser.objects.create_user(
            google_subject="audit-string-actor-subject",
        )
        request_id = uuid.uuid4()
        source_ip_hash = "a" * 64
        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            actor=actor,
            source_ip_hash=source_ip_hash,
            request_id=request_id,
        )

        rendered = str(event)

        self.assertNotIn("\n", rendered)
        self.assertNotIn("\r", rendered)
        self.assertIn(SecurityEventType.LOGIN_FAILED, rendered)
        self.assertNotIn(str(actor.id), rendered)
        self.assertNotIn(str(request_id), rendered)
        self.assertNotIn(source_ip_hash, rendered)

        invalid_event = SecurityEvent(
            event_type="forged\nentry\rnext",
            request_id=uuid.uuid4(),
        )
        invalid_rendered = str(invalid_event)

        self.assertNotIn("\n", invalid_rendered)
        self.assertNotIn("\r", invalid_rendered)
        self.assertIn("invalid_event_type", invalid_rendered)

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

    def test_event_type_database_constraint_rejects_invalid_insert(self) -> None:
        """Verify the database rejects invalid types that bypass model hooks.

        Args:
            self: The test case instance.
        """
        invalid_event = SecurityEvent(
            event_type="message_body_logged",
            request_id=uuid.uuid4(),
            occurred_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                # Using bulk_create, it is the database constraints that throw the exception.
                SecurityEvent._base_manager.bulk_create([invalid_event])

        self.assertFalse(
            SecurityEvent._base_manager.filter(pk=invalid_event.pk).exists()
        )
