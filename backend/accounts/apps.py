"""Django application configuration for federated accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = 'backend.accounts'
