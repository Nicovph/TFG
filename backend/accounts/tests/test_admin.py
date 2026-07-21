"""Tests for account administration permissions and passwordless behavior."""

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, Group
from django.http import HttpRequest
from django.test import RequestFactory, TestCase

from ..admin import CustomUserAdmin
from ..models import CustomUser


class CustomUserAdminTests(TestCase):
    """Verify account administration remains restricted and passwordless."""

    def setUp(self) -> None:
        """Create request factory and admin instance for admin permission tests.

        Args:
            self: The test case instance.
        """
        self.factory = RequestFactory()
        self.model_admin = CustomUserAdmin(CustomUser, admin.site)

    def _request_for(self, user: CustomUser | AnonymousUser) -> HttpRequest:
        """Build an admin request carrying the supplied user.

        Args:
            user: The authenticated or anonymous user attached to the request.

        Returns:
            A request object suitable for ModelAdmin permission checks.
        """
        request = self.factory.get("/admin/accounts/customuser/")
        request.user = user
        return request

    def test_admin_denies_anonymous_and_staff_non_superuser_access(self) -> None:
        """Allow user administration only to active superusers.

        Args:
            self: The test case instance.
        """
        anonymous_request = self._request_for(AnonymousUser())
        staff_user = CustomUser.objects.create_staff_user(
            google_subject="google-subject-staff",
        )
        staff_request = self._request_for(staff_user)

        self.assertFalse(self.model_admin.has_module_permission(anonymous_request))
        self.assertFalse(self.model_admin.has_view_permission(staff_request))
        self.assertFalse(self.model_admin.has_change_permission(staff_request))

    def test_permission_helper_requires_active_superuser_staff_access(self) -> None:
        """Reuse the same permission guard for admin-level account access."""
        anonymous_request = self._request_for(AnonymousUser())
        staff_user = CustomUser.objects.create_staff_user(
            google_subject="google-subject-helper",
        )
        staff_request = self._request_for(staff_user)
        superuser = CustomUser.objects.create_superuser(
            google_subject="google-subject-helper-superuser",
        )
        superuser_request = self._request_for(superuser)

        self.assertFalse(self.model_admin._can_manage_accounts(anonymous_request))
        self.assertFalse(self.model_admin._can_manage_accounts(staff_request))
        self.assertTrue(self.model_admin._can_manage_accounts(superuser_request))

    def test_admin_allows_active_superuser_and_blocks_manual_lifecycle(self) -> None:
        """Allow inspection by superuser while blocking add and delete paths.

        Args:
            self: The test case instance.
        """
        superuser = CustomUser.objects.create_superuser(
            google_subject="google-subject-admin",
        )
        request = self._request_for(superuser)

        self.assertTrue(self.model_admin.has_module_permission(request))
        self.assertTrue(self.model_admin.has_view_permission(request, superuser))
        self.assertTrue(self.model_admin.has_change_permission(request, superuser))
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request, superuser))

    def test_admin_marks_self_authorization_flags_readonly(self) -> None:
        """Prevent accidental self-revocation of critical admin flags.

        Args:
            self: The test case instance.
        """
        superuser = CustomUser.objects.create_superuser(
            google_subject="google-subject-self-admin",
        )
        request = self._request_for(superuser)

        readonly_fields = self.model_admin.get_readonly_fields(
            request,
            obj=superuser,
        )

        self.assertIn("is_active", readonly_fields)
        self.assertIn("is_staff", readonly_fields)
        self.assertIn("is_superuser", readonly_fields)

    def test_admin_does_not_expose_unused_permission_management(self) -> None:
        """Hide group and individual permission management from the admin.

        Args:
            self: The test case instance.
        """
        configured_fields = {
            field_name
            for _heading, options in self.model_admin.fieldsets
            for field_name in options["fields"]
        }

        self.assertFalse(admin.site.is_registered(Group))
        self.assertNotIn("groups", configured_fields)
        self.assertNotIn("user_permissions", configured_fields)
        self.assertEqual(self.model_admin.filter_horizontal, ())
