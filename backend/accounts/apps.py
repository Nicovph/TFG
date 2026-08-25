"""Django application configuration for federated accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Expose the federated account application with a Spanish admin label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = 'backend.accounts'
    verbose_name = "Cuentas"
