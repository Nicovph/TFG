"""Tests for bounded, privacy-minimised interpretation audit policies."""

from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from backend.accounts.models import CustomUser

from ..rate_limit_audit import record_llm_rate_limit_best_effort


@override_settings(
    LLM_QUOTA_HMAC_KEY="interpretation-audit-test-key-at-least-32-bytes",
)
class InterpretationAuditPolicyTests(SimpleTestCase):
    """Verify audit deduplication failures cannot amplify database writes."""

    # Replaces a real function in a module with a MagicMock object.
    @patch("backend.interpretation.rate_limit_audit.record_security_event_best_effort")
    @patch("backend.interpretation.rate_limit_audit.get_llm_transient_cache")
    def test_cache_failure_skips_audit_write_and_logs_no_private_detail(
        self,
        get_cache_mock: Mock,
        record_event_mock: Mock,
    ) -> None:
        """Prefer bounded audit loss to one database insert per rejection.

        Args:
            get_cache_mock: Mocked transient-cache resolver.
            record_event_mock: Mocked persistent audit isolation service.
        """
        actor = CustomUser(id=uuid.uuid4(), google_subject="synthetic-subject")
        transient_cache = Mock()
        transient_cache.add.side_effect = RuntimeError("private-cache-endpoint")
        get_cache_mock.return_value = transient_cache

        with self.assertLogs(
            "backend.interpretation.rate_limit_audit",
            level="WARNING",
        ) as logs:
            recorded = record_llm_rate_limit_best_effort(
                actor=actor,
                retry_after_seconds=17,
            )

        rendered_logs = " ".join(logs.output)
        self.assertFalse(recorded)
        record_event_mock.assert_not_called()
        self.assertNotIn(str(actor.id), rendered_logs)
        self.assertNotIn("private-cache-endpoint", rendered_logs)
