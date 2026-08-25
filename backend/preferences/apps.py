"""Django application configuration for user preferences."""

from django.apps import AppConfig


class PreferencesConfig(AppConfig):
    """Expose user preferences with a Spanish administration label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'backend.preferences'
    verbose_name = "Preferencias"
