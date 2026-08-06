"""Minimal pseudonymous state for application-enforced LLM quotas."""

from django.core.validators import RegexValidator
from django.db import models


subject_hash_validator = RegexValidator(
    regex=r"\A[0-9a-f]{64}\Z",
    message=(
        "El identificador de cuota debe contener exactamente "
        "64 caracteres hexadecimales en minúsculas."
    ),
    code="invalid_llm_quota_subject",
)


class LLMRateLimitState(models.Model):
    """Store fixed-window quota counters without user or provider content."""

    subject_hash = models.CharField(
        primary_key=True,
        max_length=64,
        validators=[subject_hash_validator],
        editable=False,
    )
    minute_started_at = models.DateTimeField()
    minute_requests = models.PositiveIntegerField(default=0)
    minute_tokens = models.PositiveIntegerField(default=0)
    day_started_at = models.DateTimeField()
    day_requests = models.PositiveIntegerField(default=0)
    day_tokens = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Disable default permissions and optimize retention cleanup."""

        # Avoid creating add, change, delete, or view permissions for this state.
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    subject_hash__regex=r"^[0-9a-f]{64}$",
                ),
                name="interpret_quota_subject_hash_format",
            ),
        ]
        indexes = [
            models.Index(
                fields=("updated_at",),
                name="interpret_quota_updated_idx",
            ),
        ]

    def __str__(self) -> str:
        """Return a non-identifying label for diagnostics.

        Returns:
            A fixed label that never exposes the pseudonymous subject hash.
        """
        return "Estado de cuota LLM"
