"""Administration configuration for federated user accounts.

This module exposes read-only federated identity metadata and allows
authorized administrators to manage account authorization state. Accounts
cannot be created or deleted through the Django admin, and unused group and
individual permission management is not exposed.
"""

from django.contrib import admin
from django.contrib.auth.models import Group
from django.http import HttpRequest

from .models import CustomUser


# Remove unused group management from the default Django admin site.
admin.site.unregister(Group)


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    """Expose identity and authorization state without local credentials."""

    # Fields shown in the changelist view to identify user status quickly.
    list_display = (
        "id",
        "is_active",
        "is_staff",
        "is_superuser",
        "date_joined",
        "last_login",
    )

    # Filters available in the sidebar to narrow results by authorization state.
    list_filter = ("is_active", "is_staff", "is_superuser")

    # Exact-match search fields to find users by UUID.
    search_fields = ("id__exact",)
    search_help_text = "Introduce el UUID completo del usuario para buscar."

    # Order users by creation date, newest first.
    ordering = ("-date_joined",)

    # Make audit-relevant identity fields read-only in the admin form.
    readonly_fields = (
        "id",
        "google_subject",
        "date_joined",
        "last_login",
        "updated_at",
    )

    # Separate federated identity metadata from authorization settings.
    fieldsets = (
        (
            "Identidad federada",
            {
                "fields": (
                    "id",
                    "google_subject",
                    "date_joined",
                    "last_login",
                    "updated_at",
                )
            },
        ),
        (
            "Autorización",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
    )

    @staticmethod
    def _can_manage_accounts(request: HttpRequest) -> bool:
        """Allow account administration only to active staff superusers.

        Args:
            request: The HTTP request object.

        Returns:
            True if the current user is authenticated, active, staff and superuser.
        """
        user = request.user

        return bool(
            user.is_authenticated
            and user.is_active
            and user.is_staff
            and user.is_superuser
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent manual creation of accounts from the Django admin.

        Users should be created only via a validated OpenID Connect login flow.
        
        Args:
            request: The HTTP request object.
        
        Returns:
            Always False.
        """
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: CustomUser | None = None,
    ) -> bool:
        """Disable deletion so audit attribution for user accounts remains intact.
        
        Args:
            request: The HTTP request object.
            obj: The user object being deleted (optional).
        
        Returns:
            Always False.
        """
        return False
    
    # Prevent all bulk operations on user accounts.
    # Prevents superusers from accidentally deleting or modifying multiple accounts at 
    # once for security and audit integrity reasons.
    actions = None

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Show this model in the admin index only to active staff superusers.
        
        Args:
            request: The HTTP request object.
        
        Returns:
            True if the user is authenticated, active, staff and superuser.
        """
        return self._can_manage_accounts(request)

    # Staff and no superuser accounts should not be able to view user records.
    def has_view_permission(
        self,
        request: HttpRequest,
        obj: CustomUser | None = None,
    ) -> bool:
        """Allow only active staff superusers to view user records in the admin.
        
        Args:
            request: The HTTP request object.
            obj: The user object being viewed (optional).
        
        Returns:
            True if the user is authenticated, active, staff and superuser.
        """
        return self._can_manage_accounts(request)

    # Staff and no superuser accounts should not be able to change user records.
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: CustomUser | None = None,
    ) -> bool:
        """Allow only active staff superusers to change user records in the admin.
        
        Args:
            request: The HTTP request object.
            obj: The user object being changed (optional).
        
        Returns:
            True if the user is authenticated, active, staff and superuser.
        """
        return self._can_manage_accounts(request)
    
    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: CustomUser | None = None,
    ) -> tuple[str, ...]:
        """Return the readonly fields for the current admin form.

        Disallow self-modification of critical authorization flags when an
        administrator is editing their own account.
        
        Args:
            request: The HTTP request object.
            obj: The user object being edited (optional).
        
        Returns:
            A tuple of field names that should be read-only.
        """
        # Start from the default readonly fields defined by ModelAdmin.
        readonly = list(
            super().get_readonly_fields(request, obj)
        )

        # When an admin is editing their own user record, prevent changes to
        # authorization state flags so they cannot accidentally revoke their
        # own superuser or staff privileges.
        if obj is not None and obj.pk == request.user.pk:
            readonly.extend(
                (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            )

        # Preserve ordering and remove duplicate entries before returning.
        return tuple(dict.fromkeys(readonly))
