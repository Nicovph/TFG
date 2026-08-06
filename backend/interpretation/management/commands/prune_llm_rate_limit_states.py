"""Delete expired pseudonymous LLM quota counters on explicit invocation
    using python manage.py prune_llm_rate_limit_states."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from backend.interpretation.models import LLMRateLimitState


class Command(BaseCommand):
    """Apply the configured quota-state retention policy manually."""

    help = (
        "Delete pseudonymous LLM quota states older than the configured "
        "retention period."
    )

    def handle(self, *_args: object, **_options: object) -> None:
        """Delete expired quota rows without exposing their subject hashes.

        Args:
            *_args: Positional command arguments retained for Django
                compatibility.
            **_options: Standard Django command options.
        """
        cutoff = timezone.now() - timedelta(
            days=settings.LLM_RATE_LIMIT_STATE_RETENTION_DAYS
        )
        # updated_at__lt is used to retrieve database records where the updated_at timestamp is 
        # strictly earlier than a specified cutoff date or datetime.
        deleted_count, _deleted_by_model = (
            LLMRateLimitState.objects.filter(
                updated_at__lt=cutoff,
            ).delete()
        )

        # Aggregate output is sufficient for operations and never discloses
        # pseudonymous subject hashes or user-derived content.
        self.stdout.write(
            self.style.SUCCESS(
                f"Estados de cuota LLM eliminados: {deleted_count}."
            )
        )
