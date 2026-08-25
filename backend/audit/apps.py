"""Django application configuration for security audit events."""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Expose the security audit application with a Spanish admin label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'backend.audit'
    verbose_name = "Auditoría"
