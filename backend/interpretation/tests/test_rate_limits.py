"""Database tests for privacy-minimised transactional LLM quotas."""

import re
from datetime import UTC, datetime
from queue import Queue
from threading import Barrier, Thread
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    transaction,
)
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from backend.accounts.models import CustomUser

from ..models import LLMRateLimitState
from ..rate_limits import (
    LlmQuotaReservationTooLarge,
    LlmRateLimitExceeded,
    _subject_hash,
    reserve_llm_provider_attempt_quota,
    reserve_llm_user_request_quota,
    validate_llm_provider_attempt_capacity,
)


TEST_QUOTA_HMAC_KEY = "quota-tests-only-key-material-32-bytes"


@override_settings(LLM_QUOTA_HMAC_KEY=TEST_QUOTA_HMAC_KEY)
class LlmRateLimitTests(TestCase):
    """Verify quotas use only pseudonymous counters and fixed windows."""

    def setUp(self) -> None:
        """Create a federated user without profile data."""
        self.user = CustomUser.objects.create_user(
            google_subject="rate-limit-subject",
        )

    @override_settings(
        LLM_USER_REQUESTS_PER_MINUTE=1,
        LLM_USER_REQUESTS_PER_DAY=10,
        LLM_USER_TOKENS_PER_MINUTE=5000,
        LLM_USER_TOKENS_PER_DAY=50000,
        LLM_GLOBAL_REQUESTS_PER_MINUTE=10,
        LLM_GLOBAL_REQUESTS_PER_DAY=100,
        LLM_GLOBAL_TOKENS_PER_MINUTE=10000,
        LLM_GLOBAL_TOKENS_PER_DAY=100000,
    )
    def test_user_minute_quota_rejects_second_reservation(self) -> None:
        """Enforce the user window before a second logical request."""
        now = timezone.now().replace(second=10, microsecond=0)
        reserve_llm_user_request_quota(user_id=self.user.id, now=now)

        with self.assertRaises(LlmRateLimitExceeded) as raised:
            reserve_llm_user_request_quota(
                user_id=self.user.id,
                now=now,
            )

        self.assertGreaterEqual(raised.exception.retry_after_seconds, 1)
        self.assertLessEqual(raised.exception.retry_after_seconds, 50)

    def test_states_store_no_user_id_or_content(self) -> None:
        """Persist only two HMAC subject rows and numeric counters."""
        reserve_llm_user_request_quota(user_id=self.user.id)
        reserve_llm_provider_attempt_quota(
            user_id=self.user.id,
            estimated_tokens=100,
        )

        states = list(LLMRateLimitState.objects.all())
        self.assertEqual(len(states), 2)

        for state in states:
            self.assertEqual(len(state.subject_hash), 64)
            self.assertNotIn(str(self.user.id), state.subject_hash)
            self.assertEqual(str(state), "Estado de cuota LLM")
            self.assertEqual(state.minute_requests, 1)
            self.assertEqual(state.day_requests, 1)

    def test_provider_retry_attributes_tokens_without_repeating_user_request(
        self,
    ) -> None:
        """Protect fair token sharing while preserving one logical user action."""
        reserve_llm_user_request_quota(user_id=self.user.id)
        reserve_llm_provider_attempt_quota(
            user_id=self.user.id,
            estimated_tokens=100,
        )
        reserve_llm_provider_attempt_quota(
            user_id=self.user.id,
            estimated_tokens=100,
        )

        user_state = LLMRateLimitState.objects.get(
            subject_hash=_subject_hash(f"user:{self.user.id.hex}")
        )
        global_state = LLMRateLimitState.objects.get(
            subject_hash=_subject_hash("global")
        )

        self.assertEqual(user_state.minute_requests, 1)
        self.assertEqual(user_state.minute_tokens, 200)
        self.assertEqual(global_state.minute_requests, 2)
        self.assertEqual(global_state.minute_tokens, 200)

    @override_settings(
        LLM_USER_REQUESTS_PER_MINUTE=1,
        LLM_USER_REQUESTS_PER_DAY=1,
        LLM_USER_TOKENS_PER_MINUTE=5000,
        LLM_USER_TOKENS_PER_DAY=50000,
        LLM_GLOBAL_REQUESTS_PER_MINUTE=10,
        LLM_GLOBAL_REQUESTS_PER_DAY=100,
        LLM_GLOBAL_TOKENS_PER_MINUTE=10000,
        LLM_GLOBAL_TOKENS_PER_DAY=100000,
    )
    def test_retry_after_waits_for_the_last_exhausted_window(self) -> None:
        """Return the daily reset when minute and day quotas are both exhausted."""
        now = datetime(2026, 7, 30, 10, 0, 40, tzinfo=UTC)
        reserve_llm_user_request_quota(
            user_id=self.user.id,
            now=now,
        )

        with self.assertRaises(LlmRateLimitExceeded) as raised:
            reserve_llm_user_request_quota(
                user_id=self.user.id,
                now=now,
            )

        self.assertEqual(raised.exception.retry_after_seconds, 50_360)

    def test_impossible_reservation_is_not_reported_as_temporary(self) -> None:
        """Reject attempts that cannot fit in an empty minute or day window."""
        impossible_limits = (
            (99, 1000),
            (1000, 99),
        )

        for tokens_per_minute, tokens_per_day in impossible_limits:
            with self.subTest(
                tokens_per_minute=tokens_per_minute,
                tokens_per_day=tokens_per_day,
            ), override_settings(
                LLM_USER_REQUESTS_PER_MINUTE=3,
                LLM_USER_REQUESTS_PER_DAY=30,
                LLM_USER_TOKENS_PER_MINUTE=tokens_per_minute,
                LLM_USER_TOKENS_PER_DAY=tokens_per_day,
                LLM_GLOBAL_REQUESTS_PER_MINUTE=10,
                LLM_GLOBAL_REQUESTS_PER_DAY=100,
                LLM_GLOBAL_TOKENS_PER_MINUTE=10000,
                LLM_GLOBAL_TOKENS_PER_DAY=100000,
            ):
                with self.assertRaises(LlmQuotaReservationTooLarge):
                    validate_llm_provider_attempt_capacity(
                        estimated_tokens=100,
                    )

                self.assertFalse(LLMRateLimitState.objects.exists())

    def test_quota_times_are_utc_aware_and_never_accept_naive_values(
        self,
    ) -> None:
        """Normalize aware test instants and reject ambiguous naive datetimes."""
        sao_paulo_time = datetime(
            2026,
            7,
            30,
            21,
            15,
            42,
            tzinfo=ZoneInfo("America/Sao_Paulo"),
        )
        reserve_llm_user_request_quota(
            user_id=self.user.id,
            now=sao_paulo_time,
        )

        expected_minute = datetime(2026, 7, 31, 0, 15, tzinfo=UTC)
        expected_day = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)

        for state in LLMRateLimitState.objects.all():
            self.assertEqual(state.minute_started_at, expected_minute)
            self.assertEqual(state.day_started_at, expected_day)

        with self.assertRaisesMessage(
            ValueError,
            "La marca temporal de la cuota debe incluir zona horaria.",
        ):
            reserve_llm_user_request_quota(
                user_id=self.user.id,
                now=datetime(2026, 7, 31, 0, 16),
            )

    def test_user_quota_requires_the_internal_uuid_type(self) -> None:
        """Reject alternate textual or object representations of user identity."""
        with self.assertRaisesMessage(
            TypeError,
            "El identificador interno del usuario debe ser un UUID.",
        ):
            reserve_llm_user_request_quota(
                user_id=str(self.user.id),  # type: ignore[arg-type]
            )

        self.assertFalse(LLMRateLimitState.objects.exists())

    def test_subject_hash_validator_describes_only_the_stored_format(self) -> None:
        """Reject a malformed quota subject with a format-only error."""
        now = timezone.now()
        state = LLMRateLimitState(
            subject_hash="not-an-hmac",
            minute_started_at=now,
            day_started_at=now,
        )

        with self.assertRaises(ValidationError) as raised:
            state.full_clean()

        self.assertIn("subject_hash", raised.exception.message_dict)
        self.assertIn(
            (
                "El identificador de cuota debe contener exactamente "
                "64 caracteres hexadecimales en minúsculas."
            ),
            raised.exception.message_dict["subject_hash"],
        )

    def test_subject_hash_is_lowercase_sha256_hexadecimal(self) -> None:
        """Generate only the closed storage format from an internal subject."""
        subject_hash = _subject_hash(f"user:{self.user.id}")

        self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{64}", subject_hash))
        self.assertNotIn(str(self.user.id), subject_hash)

    def test_subject_hash_separates_user_and_global_domains(self) -> None:
        """Keep global and per-user quota subjects cryptographically distinct."""
        self.assertNotEqual(
            _subject_hash(f"user:{self.user.id}"),
            _subject_hash("global"),
        )

    def test_quota_hmac_key_rotation_changes_the_subject(self) -> None:
        """Document that rotating the dedicated key restarts quota identity."""
        subject = f"user:{self.user.id}"

        with override_settings(LLM_QUOTA_HMAC_KEY="a" * 32):
            old_subject_hash = _subject_hash(subject)

        with override_settings(LLM_QUOTA_HMAC_KEY="b" * 32):
            new_subject_hash = _subject_hash(subject)

        self.assertNotEqual(old_subject_hash, new_subject_hash)

    def test_quota_hmac_key_is_required_and_has_a_minimum_length(self) -> None:
        """Reject absent or too-short quota pseudonymization keys."""
        for invalid_key in ("", "short-key"):
            with self.subTest(invalid_key=invalid_key):
                with override_settings(LLM_QUOTA_HMAC_KEY=invalid_key):
                    with self.assertRaises(ImproperlyConfigured):
                        _subject_hash("global")

    def test_internal_quota_state_is_not_registered_in_admin(self) -> None:
        """Keep pseudonymous operational counters outside Django Admin."""
        self.assertFalse(admin.site.is_registered(LLMRateLimitState))


class LlmRateLimitDatabaseConstraintTests(TransactionTestCase):
    """Verify PostgreSQL enforces the quota subject storage invariant."""

    def test_database_rejects_a_non_hexadecimal_subject_hash(self) -> None:
        """Reject malformed direct ORM inserts even when validation is bypassed."""
        now = timezone.now()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LLMRateLimitState.objects.create(
                    subject_hash="g" * 64,
                    minute_started_at=now,
                    day_started_at=now,
                )


@override_settings(
    LLM_QUOTA_HMAC_KEY=TEST_QUOTA_HMAC_KEY,
    LLM_USER_REQUESTS_PER_MINUTE=1,
    LLM_USER_REQUESTS_PER_DAY=10,
    LLM_USER_TOKENS_PER_MINUTE=5000,
    LLM_USER_TOKENS_PER_DAY=50000,
    LLM_GLOBAL_REQUESTS_PER_MINUTE=10,
    LLM_GLOBAL_REQUESTS_PER_DAY=100,
    LLM_GLOBAL_TOKENS_PER_MINUTE=10000,
    LLM_GLOBAL_TOKENS_PER_DAY=100000,
)
class LlmRateLimitConcurrencyTests(TransactionTestCase):
    """Verify concurrent reservations serialize their quota decision."""

    def setUp(self) -> None:
        """Create a committed user visible to independent test connections."""
        self.user = CustomUser.objects.create_user(
            google_subject="rate-limit-concurrency-subject",
        )

    def _reserve_concurrently(
        self,
        *,
        barrier: Barrier,
        outcomes: Queue[object],
    ) -> None:
        """Reserve quota from an independent thread-local database connection.

        Args:
            barrier: Synchronization point used to overlap both reservations.
            outcomes: Thread-safe queue receiving the result or unexpected error.
        """
        close_old_connections()

        try:
            barrier.wait(timeout=5)
            reserve_llm_user_request_quota(
                user_id=self.user.id,
            )
        except LlmRateLimitExceeded:
            outcomes.put("limited")
        except Exception as exc:
            outcomes.put(exc)
        else:
            outcomes.put("accepted")
        finally:
            connection.close()

    def test_concurrent_requests_cannot_both_pass_a_single_request_limit(
        self,
    ) -> None:
        """Admit exactly one of two simultaneous requests for the same user."""
        if connection.vendor != "postgresql":
            self.skipTest(
                "La prueba de concurrencia con bloqueo de filas requiere PostgreSQL."
            )

        barrier = Barrier(2)
        outcomes: Queue[object] = Queue()
        threads = [
            Thread(
                target=self._reserve_concurrently,
                kwargs={
                    "barrier": barrier,
                    "outcomes": outcomes,
                },
                daemon=True,
            )
            for _ in range(2)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        results = [outcomes.get_nowait() for _ in threads]
        unexpected_errors = [
            result for result in results if isinstance(result, Exception)
        ]

        if unexpected_errors:
            self.fail(
                "Error inesperado durante la prueba concurrente de cuotas: "
                f"{unexpected_errors!r}"
            )

        self.assertCountEqual(results, ("accepted", "limited"))

        states = list(LLMRateLimitState.objects.all())
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].minute_requests, 1)
        self.assertEqual(states[0].day_requests, 1)
