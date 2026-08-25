"""Django application configuration for interpretation features."""

from django.apps import AppConfig


class InterpretationConfig(AppConfig):
    """Configure interpretation models and startup validation hooks."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'backend.interpretation'
    verbose_name = "Interpretación"

    def ready(self) -> None:
        """Register interpretation system checks when Django loads the app."""
        # Importing this module registers its decorated checks exactly once as
        # part of Django's documented AppConfig.ready() lifecycle.
        from . import checks  # noqa: F401
