"""Transactional per-user and global quotas without storing user content."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .hmac_identifiers import build_llm_hmac_digest
from .models import LLMRateLimitState


@dataclass(frozen=True, slots=True)
class QuotaLimits:
    """Hold closed request and token limits for one quota subject."""

    requests_per_minute: int
    requests_per_day: int
    tokens_per_minute: int
    tokens_per_day: int


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    """Hold one subject's limits and independent counter increments."""

    limits: QuotaLimits
    request_increment: int
    token_increment: int


class LlmRateLimitExceeded(RuntimeError):
    """Indicate that an application-owned quota window is exhausted."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        """Store a bounded delay safe to expose in a Retry-After header.

        Args:
            retry_after_seconds: Seconds until the exhausted window resets.
        """
        super().__init__(
            "Se ha superado una cuota de LLM gestionada por la aplicación."
        )
        self.retry_after_seconds = max(1, retry_after_seconds)


class LlmQuotaReservationTooLarge(RuntimeError):
    """Indicate that one provider attempt can never fit in a quota window."""


def _subject_hash(value: str) -> str:
    """Create a domain-separated HMAC identifier for quota accounting.

    Turns an internal subject (UUID or fixed label) into a stable, opaque
    digest so quota counters never store raw identity.

    Args:
        value: Internal UUID or fixed global quota label.

    Returns:
        A lowercase HMAC-SHA-256 digest containing no raw identity.

    Raises:
        ImproperlyConfigured: If the quota-specific HMAC key is missing or too
            short.
    """
    return build_llm_hmac_digest(
        domain="llm-quota:v1",
        value=value,
    )


def _user_subject_hash(user_id: UUID) -> str:
    """Build one canonical HMAC subject from an authenticated local UUID.

    Args:
        user_id: Internal UUID obtained from the authenticated Django user.

    Returns:
        A stable HMAC digest that contains no raw local identifier.

    Raises:
        TypeError: If the caller does not provide a UUID instance.
    """
    if not isinstance(user_id, UUID):
        raise TypeError(
            "El identificador interno del usuario debe ser un UUID."
        )

    # UUID.hex is always 32 lowercase hexadecimal characters without hyphens,
    # preventing equivalent UUID text formats from creating different subjects.
    return _subject_hash(f"user:{user_id.hex}")


def _normalize_utc_time(now: datetime | None) -> datetime:
    """Return one aware UTC timestamp for fixed-window calculations.

    Args:
        now: Optional caller-provided timestamp, primarily for deterministic
            tests.

    Returns:
        The supplied instant normalized to UTC, or the current UTC instant.

    Raises:
        ValueError: If a naive timestamp cannot identify an absolute instant.
    """
    current_time = now or timezone.now()

    # is_naive detects a datetime without an effective UTC offset; accepting it
    # would make the quota boundary depend on an implicit local timezone.
    if timezone.is_naive(current_time):
        raise ValueError(
            "La marca temporal de la cuota debe incluir zona horaria."
        )

    return current_time.astimezone(UTC)


def _window_starts(now: datetime) -> tuple[datetime, datetime]:
    """Return UTC minute and day boundaries for deterministic counters.

    Floor `now` to the start of the current minute and day so all requests in
    the same window share one counter key; crossing the boundary opens a new
    window with a fresh quota.

    Args:
        now: Current timezone-aware timestamp.

    Returns:
        A tuple containing minute and day window start timestamps.
    """
    return (
        now.replace(second=0, microsecond=0),
        now.replace(hour=0, minute=0, second=0, microsecond=0),
    )


def _seconds_until(window_start: datetime, duration: timedelta, now: datetime) -> int:
    """Calculate a positive Retry-After value for an exhausted window.

    Args:
        window_start: Beginning of the active quota window.
        duration: Length of that window.
        now: Current timestamp.

    Returns:
        Whole seconds until reset, rounded upward.
    """
    return max(1, math.ceil((window_start + duration - now).total_seconds()))


def _reset_expired_windows(
    *,
    state: LLMRateLimitState,
    minute_start: datetime,
    day_start: datetime,
) -> None:
    """Reset counters whose fixed UTC windows have elapsed.

    Args:
        state: Locked database quota state.
        minute_start: Current UTC minute boundary.
        day_start: Current UTC day boundary.
    """
    if state.minute_started_at != minute_start:
        state.minute_started_at = minute_start
        state.minute_requests = 0
        state.minute_tokens = 0

    if state.day_started_at != day_start:
        state.day_started_at = day_start
        state.day_requests = 0
        state.day_tokens = 0


def _check_state(
    *,
    state: LLMRateLimitState,
    reservation: QuotaReservation,
    now: datetime,
) -> None:
    """Reject a reservation that would exceed any closed quota.

    Args:
        state: Locked and window-normalized quota state.
        reservation: Limits and independent request/token increments.
        now: Current timestamp used to calculate reset delays.

    Raises:
        LlmRateLimitExceeded: If a minute or day request/token limit would be
            exceeded.
    """
    limits = reservation.limits
    minute_exceeded = (
        state.minute_requests + reservation.request_increment
        > limits.requests_per_minute
        or state.minute_tokens + reservation.token_increment
        > limits.tokens_per_minute
    )
    day_exceeded = (
        state.day_requests + reservation.request_increment
        > limits.requests_per_day
        or state.day_tokens + reservation.token_increment
        > limits.tokens_per_day
    )
    retry_delays: list[int] = []

    if minute_exceeded:
        retry_delays.append(
            _seconds_until(
                state.minute_started_at,
                timedelta(minutes=1),
                now,
            )
        )

    if day_exceeded:
        retry_delays.append(
            _seconds_until(
                state.day_started_at,
                timedelta(days=1),
                now,
            )
        )

    if retry_delays:
        raise LlmRateLimitExceeded(
            retry_after_seconds=max(retry_delays),
        )


def _validate_reservations(
    subjects: dict[str, QuotaReservation],
) -> None:
    """Reject empty, invalid, or permanently impossible reservations.

    Args:
        subjects: HMAC subjects and their closed reservation policies.

    Raises:
        LlmQuotaReservationTooLarge: If one increment can never fit.
        ValueError: If no subject exists or an increment is invalid.
    """
    if not subjects:
        raise ValueError("Debe existir al menos un sujeto de cuota.")

    for reservation in subjects.values():
        if (
            reservation.request_increment < 0
            or reservation.token_increment < 0
        ):
            raise ValueError(
                "Los incrementos de cuota no pueden ser negativos."
            )

        if (
            reservation.request_increment == 0
            and reservation.token_increment == 0
        ):
            raise ValueError(
                "Una reserva debe incrementar solicitudes o tokens."
            )

        limits = reservation.limits

        if (
            reservation.request_increment > limits.requests_per_minute
            or reservation.request_increment > limits.requests_per_day
            or reservation.token_increment > limits.tokens_per_minute
            or reservation.token_increment > limits.tokens_per_day
        ):
            raise LlmQuotaReservationTooLarge(
                "La solicitud no cabe en una ventana de cuota vacía."
            )


def _user_quota_limits() -> QuotaLimits:
    """Build the server-owned limits for one authenticated user.

    Returns:
        Closed per-user request and token limits.
    """
    return QuotaLimits(
        requests_per_minute=settings.LLM_USER_REQUESTS_PER_MINUTE,
        requests_per_day=settings.LLM_USER_REQUESTS_PER_DAY,
        tokens_per_minute=settings.LLM_USER_TOKENS_PER_MINUTE,
        tokens_per_day=settings.LLM_USER_TOKENS_PER_DAY,
    )


def _global_quota_limits() -> QuotaLimits:
    """Build the shared limits protecting the Groq organization quota.

    Returns:
        Closed application-wide request and token limits.
    """
    return QuotaLimits(
        requests_per_minute=settings.LLM_GLOBAL_REQUESTS_PER_MINUTE,
        requests_per_day=settings.LLM_GLOBAL_REQUESTS_PER_DAY,
        tokens_per_minute=settings.LLM_GLOBAL_TOKENS_PER_MINUTE,
        tokens_per_day=settings.LLM_GLOBAL_TOKENS_PER_DAY,
    )


@transaction.atomic
def _reserve_subject_quotas(
    *,
    subjects: dict[str, QuotaReservation],
    now: datetime | None = None,
) -> None:
    """Atomically reserve request and token capacity for selected subjects.

    Applies pessimistic locking (`select_for_update`) to prevent race
    conditions and sorts subject keys deterministically to avoid database
    deadlocks. Enforces fixed-window rate limits in an all-or-nothing
    transaction.

    Args:
        subjects: HMAC subjects and their independent quota reservations.
        now: Optional deterministic timestamp used by tests.

    Raises:
        LlmQuotaReservationTooLarge: If one attempt can never fit.
        LlmRateLimitExceeded: If any selected quota is exhausted.
        ValueError: If the subject collection or increments are invalid.
    """
    _validate_reservations(subjects)
    current_time = _normalize_utc_time(now)
    minute_start, day_start = _window_starts(current_time)

    for subject_hash in sorted(subjects):
        LLMRateLimitState.objects.get_or_create(
            subject_hash=subject_hash,
            defaults={
                "minute_started_at": minute_start,
                "day_started_at": day_start,
            },
        )

    locked_states = {
        state.subject_hash: state
        for state in LLMRateLimitState.objects.select_for_update()
        .filter(subject_hash__in=subjects)
        .order_by("subject_hash")
    }

    for subject_hash, reservation in subjects.items():
        state = locked_states[subject_hash]
        _reset_expired_windows(
            state=state,
            minute_start=minute_start,
            day_start=day_start,
        )
        _check_state(
            state=state,
            reservation=reservation,
            now=current_time,
        )

    for subject_hash, state in locked_states.items():
        reservation = subjects[subject_hash]
        state.minute_requests += reservation.request_increment
        state.minute_tokens += reservation.token_increment
        state.day_requests += reservation.request_increment
        state.day_tokens += reservation.token_increment
        state.save(
            update_fields=(
                "minute_started_at",
                "minute_requests",
                "minute_tokens",
                "day_started_at",
                "day_requests",
                "day_tokens",
                "updated_at",
            )
        )


def validate_llm_provider_attempt_capacity(
    *,
    estimated_tokens: int,
) -> None:
    """Reject an attempt that cannot fit in any empty token window.

    Args:
        estimated_tokens: Padded approximate reservation for one provider call.

    Raises:
        LlmQuotaReservationTooLarge: If one attempt can never fit.
        ValueError: If the token estimate is not positive.
    """
    if estimated_tokens < 1:
        raise ValueError(
            "La reserva estimada de tokens debe ser positiva."
        )

    for limits in (_user_quota_limits(), _global_quota_limits()):
        if (
            estimated_tokens > limits.tokens_per_minute
            or estimated_tokens > limits.tokens_per_day
        ):
            raise LlmQuotaReservationTooLarge(
                "La solicitud no cabe en una ventana de cuota vacía."
            )


def reserve_llm_user_request_quota(
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> None:
    """Reserve one accepted logical request for an authenticated user.

    The logical counter protects the application endpoint even if local
    backpressure or provider configuration prevents an external call. Token
    capacity is reserved separately only for attempts that can reach Groq.

    Args:
        user_id: Authenticated user's internal UUID obtained from the session.
        now: Optional deterministic timestamp used by tests.

    Raises:
        LlmRateLimitExceeded: If the user's request quota is exhausted.
        TypeError: If the internal user identifier is not a UUID.
    """
    _reserve_subject_quotas(
        subjects={
            _user_subject_hash(user_id): QuotaReservation(
                limits=_user_quota_limits(),
                request_increment=1,
                token_increment=0,
            ),
        },
        now=now,
    )


def reserve_llm_provider_attempt_quota(
    *,
    user_id: UUID,
    estimated_tokens: int,
    now: datetime | None = None,
) -> None:
    """Reserve quota immediately before one potential external provider call.

    Every first attempt and retry attributes its estimated tokens to the user and
    consumes shared request and token capacity. The logical user request remains
    reserved exactly once by `reserve_llm_user_request_quota`.

    Args:
        user_id: Authenticated user's internal UUID obtained from the session.
        estimated_tokens: Padded approximate reservation for one provider call.
        now: Optional deterministic timestamp used by tests.

    Raises:
        LlmQuotaReservationTooLarge: If one attempt can never fit.
        LlmRateLimitExceeded: If user token or shared provider quota is
            exhausted.
        TypeError: If the internal user identifier is not a UUID.
        ValueError: If the token estimate is not positive.
    """
    validate_llm_provider_attempt_capacity(
        estimated_tokens=estimated_tokens,
    )

    _reserve_subject_quotas(
        subjects={
            _user_subject_hash(user_id): QuotaReservation(
                limits=_user_quota_limits(),
                request_increment=0,
                token_increment=estimated_tokens,
            ),
            _subject_hash("global"): QuotaReservation(
                limits=_global_quota_limits(),
                request_increment=1,
                token_increment=estimated_tokens,
            ),
        },
        now=now,
    )
