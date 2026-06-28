"""Read-only administration for security audit events.

This module configures the Django admin interface to display audit records
without allowing creation, modification, or deletion from the admin site.
Audit data must be managed through application workflows or retention jobs.
"""

from django.contrib import admin
from django.http import HttpRequest

from .models import SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    """Admin view for inspection-only security event records."""

    # Display key event metadata in the changelist view.
    list_display = ("event_type", "actor", "request_id", "occurred_at")

    # Use joined loading for the actor relation so the changelist can render the
    # related user without additional database queries.
    list_select_related = ("actor",)

    # Allow filtering by event type and event timestamp.
    list_filter = ("event_type", "occurred_at")

    # Provide exact-match search fields for UUIDs and actor references.
    search_fields = ("id__exact", "actor__id__exact", "request_id__exact")

    search_help_text = ("Buscar por UUID completo del evento, UUID del actor o request_id.")

    # Show the newest events first.
    ordering = ("-occurred_at",)

    # Make all relevant audit fields read-only in the admin form.
    readonly_fields = (
        "id",
        "event_type",
        "actor",
        "actor_id_snapshot",
        "source_ip_hash",
        "request_id",
        "occurred_at",
    )

    @staticmethod # Because is a utility method that does not depend on the instance.
    def _can_view_audit_events(request: HttpRequest) -> bool:
        """Allow audit inspection only to active staff superusers.

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

    def has_module_permission(self, request: HttpRequest) -> bool:
        """Show the audit module only to authorized administrators.

        Args:
            request: The HTTP request object.

        Returns:
            True if the current user can inspect audit events; False otherwise.
        """
        return self._can_view_audit_events(request)

    def has_view_permission(
        self,
        request: HttpRequest,
        obj: SecurityEvent | None = None,
    ) -> bool:
        """Allow only authorized administrators to inspect audit records.

        Args:
            request: The HTTP request object.
            obj: The audit event being viewed (optional).

        Returns:
            True if the current user can inspect audit events; False otherwise.
        """
        return self._can_view_audit_events(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disallow manual creation of audit events through the admin.
        
        Args:
            request: The HTTP request object.
        
        Returns:
            Always False.
        """
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: SecurityEvent | None = None,
    ) -> bool:
        """Disallow editing of audit records to preserve append-only integrity.
        
        Args:
            request: The HTTP request object.
            obj: The audit event being changed (optional).
        
        Returns:
            Always False.
        """
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: SecurityEvent | None = None,
    ) -> bool:
        """Disallow deletion of audit records from the admin.

        Removal of audit data should only occur via a controlled retention
        process outside of the admin interface.
        
        Args:
            request: The HTTP request object.
            obj: The audit event being deleted (optional).
        
        Returns:
            Always False.
        """
        return False