"""Tests for read-only security event administration permissions."""

import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.test import RequestFactory, TestCase

from backend.accounts.models import CustomUser

from ..admin import SecurityEventAdmin
from ..models import SecurityEvent, SecurityEventType


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

    def test_audit_admin_applies_complete_access_matrix(self) -> None:
        """Require every authentication and privilege condition for access.

        Args:
            self: The test case instance.
        """
        staff_user = CustomUser.objects.create_staff_user(
            google_subject="audit-staff-subject",
        )
        inactive_superuser = CustomUser.objects.create_superuser(
            google_subject="inactive-audit-admin-subject",
        )
        inactive_superuser.is_active = False
        inactive_superuser.save(update_fields=("is_active",))
        non_staff_superuser = CustomUser.objects.create_superuser(
            google_subject="non-staff-audit-admin-subject",
        )
        non_staff_superuser.is_staff = False
        non_staff_superuser.save(update_fields=("is_staff",))
        active_superuser = CustomUser.objects.create_superuser(
            google_subject="active-audit-admin-subject",
        )

        cases = (
            ("anonymous", AnonymousUser(), False),
            ("staff", staff_user, False),
            ("inactive-superuser", inactive_superuser, False),
            ("non-staff-superuser", non_staff_superuser, False),
            ("active-staff-superuser", active_superuser, True),
        )

        for name, user, expected in cases:
            with self.subTest(case=name):
                request = self._request_for(user)
                self.assertIs(
                    self.model_admin.has_module_permission(request),
                    expected,
                )
                self.assertIs(
                    self.model_admin.has_view_permission(request),
                    expected,
                )

    def test_audit_admin_is_readonly_for_active_superuser_and_object(self) -> None:
        """Allow superuser inspection while blocking mutation in admin.

        Args:
            self: The test case instance.
        """
        superuser = CustomUser.objects.create_superuser(
            google_subject="audit-admin-subject",
        )
        request = self._request_for(superuser)
        event = SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGIN_FAILED,
            request_id=uuid.uuid4(),
        )
        model_field_names = {
            field.name
            for field in SecurityEvent._meta.concrete_fields
        }

        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request))
        # Check if the user can see the login failure event created in the test.
        self.assertTrue(self.model_admin.has_view_permission(request, event))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request, event))
        self.assertFalse(self.model_admin.has_delete_permission(request, event))
        self.assertTrue(
            model_field_names.issubset(set(self.model_admin.readonly_fields))
        )
        self.assertIsNone(self.model_admin.actions)

    def test_security_event_admin_is_registered(self) -> None:
        """Ensure the configured audit admin remains registered on the site.

        Args:
            self: The test case instance.
        """
        # Retrieves the registered ModelAdmin for the SecurityEvent model.
        registered_admin = admin.site.get_model_admin(SecurityEvent)

        self.assertIsInstance(registered_admin, SecurityEventAdmin)
