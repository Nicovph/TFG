"""Tests for privacy-minimized federated account behavior."""

import uuid

from django.contrib import admin
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.test import RequestFactory, TestCase

from .admin import CustomUserAdmin
from .models import CustomUser


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