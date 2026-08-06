"""Tests for explicit privacy-preserving interpretation maintenance commands."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from ..models import LLMRateLimitState


@override_settings(LLM_RATE_LIMIT_STATE_RETENTION_DAYS=2)
class PruneLlmRateLimitStatesCommandTests(TestCase):
    """Verify manual retention deletes only expired pseudonymous counters."""

    def _create_state(self, *, subject_hash: str) -> LLMRateLimitState:
        """Create one valid synthetic quota state.

        Args:
            subject_hash: Lowercase hexadecimal test subject.

        Returns:
            The newly created quota state.
        """
        now = timezone.now()
        return LLMRateLimitState.objects.create(
            subject_hash=subject_hash,
            minute_started_at=now.replace(second=0, microsecond=0),
            day_started_at=now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            ),
        )

    def test_command_prunes_only_expired_states_and_is_idempotent(self) -> None:
        """Apply configured retention repeatedly without exposing subjects."""
        expired = self._create_state(subject_hash="a" * 64)
        current = self._create_state(subject_hash="b" * 64)
        LLMRateLimitState.objects.filter(pk=expired.pk).update(
            updated_at=timezone.now() - timedelta(days=3)
        )
        first_output = StringIO()
        second_output = StringIO()

        call_command(
            "prune_llm_rate_limit_states",
            stdout=first_output,
        )
        call_command(
            "prune_llm_rate_limit_states",
            stdout=second_output,
        )

        self.assertFalse(
            LLMRateLimitState.objects.filter(pk=expired.pk).exists()
        )
        self.assertTrue(
            LLMRateLimitState.objects.filter(pk=current.pk).exists()
        )
        self.assertIn(
            "Estados de cuota LLM eliminados: 1.",
            first_output.getvalue(),
        )
        self.assertIn(
            "Estados de cuota LLM eliminados: 0.",
            second_output.getvalue(),
        )
        self.assertNotIn(expired.subject_hash, first_output.getvalue())
        self.assertNotIn(current.subject_hash, first_output.getvalue())
