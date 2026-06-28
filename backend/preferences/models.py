"""User-owned presentation and interpretation preferences."""

from django.conf import settings
from django.db import models

class Theme(models.TextChoices):
        """Closed theme choices that are safe to expose in the user interface."""

        LIGHT = "light", "Claro"
        DARK = "dark", "Oscuro"
        SYSTEM = "system", "Usar el tema del sistema"

class InterpretationDetail(models.TextChoices):
        """Closed interpretation detail levels accepted by the backend."""

        BRIEF = "brief", "Corta y directa"
        STANDARD = "standard", "Estándar"
        DETAILED = "detailed", "Detallada"

class UserPreferences(models.Model):
    """Persist the minimum preference set needed for the authenticated user."""
        
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    
    visual_support_enabled = models.BooleanField(
        default=True,
    )

    show_offensive_language = models.BooleanField(
        default=False,
    )

    show_content_warnings = models.BooleanField(
        default=True,
    )

    theme = models.CharField(
        max_length=16,
        choices=Theme.choices,
        default=Theme.SYSTEM,
    )

    interpretation_detail = models.CharField(
        max_length=16,
        choices=InterpretationDetail.choices,
        default=InterpretationDetail.STANDARD,
    )

    # The timestamp when preferences are created and not updated afterward.
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    # The timestamp when preferences are created or updated.
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        """Database-level invariants for preference enumerations."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(theme__in=Theme.values),
                name="preferences_theme_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    interpretation_detail__in=InterpretationDetail.values,
                ),
                name="preferences_interpretation_detail_valid",
            ),
        ]

    def __str__(self) -> str:
        """Reference the local UUID without loading or exposing profile data.
        
        Returns:
            A string with the format 'Preferencias de {user_id}'.
        """
        return f"Preferencias de {self.user_id}"