"""Application service orchestrating privacy-minimised LLM interpretation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import partial
from typing import Final, NoReturn
from uuid import UUID

from django.conf import settings
from django.core.cache.backends.base import BaseCache
from django.core.exceptions import ImproperlyConfigured

from backend.accounts.models import CustomUser
from backend.audit.request_context import get_current_request_id
from backend.preferences.services import get_user_preferences

from .contracts import (
    LLMInterpretationOutput,
    OutputBusinessRuleError,
    SignalKind,
    validate_output_business_rules,
)
from .hmac_identifiers import build_llm_hmac_digest
from .input_validation import (
    ContextSpeakerRelation,
    validate_and_normalize_interpretation_message,
    validate_combined_interpretation_length,
    validate_context_speaker_relation,
)
from .privacy import minimize_messages_for_provider
from .prompts import build_messages
from .provider import (
    estimate_request_tokens,
    request_interpretation,
)
from .rate_limits import (
    reserve_llm_provider_attempt_quota,
    reserve_llm_user_request_quota,
    validate_llm_provider_attempt_capacity,
)
from .transient_cache import get_llm_transient_cache


class DuplicateInterpretationRequest(RuntimeError):
    """Indicate a repeated in-flight or very recent request fingerprint."""


class InterpretationOutputRejected(RuntimeError):
    """Indicate schema-valid output rejected by application business rules."""


class InterpretationConfigurationError(RuntimeError):
    """Indicate an invalid internal configuration without exposing its detail."""


@dataclass(frozen=True, slots=True)
class InterpretationResult:
    """Hold validated provider output and deterministic presentation metadata."""

    output: LLMInterpretationOutput
    show_content_warning: bool


_RISK_SIGNAL_KINDS: Final[frozenset[SignalKind]] = frozenset(
    {
        "possible_offensive_language",
        "possible_aggression",
        "possible_cyberbullying",
    }
)
# Operational events use closed fields only and never include the message,
# fingerprint, preferences, cache endpoint, or exception text.
logger = logging.getLogger(__name__)


def _raise_interpretation_configuration_error(
    *,
    cause: ImproperlyConfigured,
) -> NoReturn:
    """Replace internal configuration detail with one sanitized service error.

    Args:
        cause: Internal Django configuration exception to preserve as the cause.

    Raises:
        InterpretationConfigurationError: Always, after recording only a closed
            operational category and trusted request correlation identifier.
    """
    logger.error(
        "llm_interpretation_configuration outcome=error "
        "error_type=internal_configuration request_id=%s",
        get_current_request_id() or "none",
    )
    raise InterpretationConfigurationError(
        "La configuración interna de interpretación no es válida."
    ) from cause


def _should_show_content_warning(
    *,
    output: LLMInterpretationOutput,
    show_content_warnings: bool,
) -> bool:
    """Derive presentation-only warning state from validated closed signals.

    Args:
        output: Schema-valid and business-rule-valid provider output.
        show_content_warnings: Server-owned presentation preference.

    Returns:
        True only when warnings are enabled and a risk signal is present.
    """
    return show_content_warnings and any(
        signal.kind in _RISK_SIGNAL_KINDS
        for signal in output.signals
    )


def _duplicate_cache_key(
    *,
    user_id: UUID,
    target_message: str,
    previous_context: str,
    previous_context_speaker: ContextSpeakerRelation,
    following_context: str,
    following_context_speaker: ContextSpeakerRelation,
    interpretation_detail: str,
    visual_support_enabled: bool,
    show_offensive_language: bool,
    show_content_warnings: bool,
) -> str:
    """Create a short-lived HMAC fingerprint without storing content.

    Args:
        user_id: Authenticated user's internal UUID obtained from the session.
        target_message: Validated target held transiently in memory.
        previous_context: Validated preceding context, possibly empty.
        previous_context_speaker: Previous author's relation to the target author.
        following_context: Validated subsequent context, possibly empty.
        following_context_speaker: Following author's relation to the target author.
        interpretation_detail: Closed detail preference affecting the prompt.
        visual_support_enabled: Whether visual concepts may be returned.
        show_offensive_language: Closed provider presentation preference.
        show_content_warnings: Closed returned-result presentation preference.

    Returns:
        A cache key containing only a keyed digest.

    Raises:
        TypeError: If the internal user identifier is not a UUID.
    """
    if not isinstance(user_id, UUID):
        raise TypeError(
            "El identificador interno del usuario debe ser un UUID."
        )

    material = json.dumps(
        {
            "following_context": following_context,
            "following_context_speaker": following_context_speaker.value,
            "interpretation_detail": interpretation_detail,
            "previous_context": previous_context,
            "previous_context_speaker": previous_context_speaker.value,
            "show_content_warnings": show_content_warnings,
            "show_offensive_language": show_offensive_language,
            "target_message": target_message,
            "user_id": user_id.hex,
            "visual_support_enabled": visual_support_enabled,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        # Stable key ordering prevents a source-level dictionary reordering
        # from changing the serialized bytes and therefore the HMAC digest.
        sort_keys=True,
    )
    digest = build_llm_hmac_digest(
        domain="llm-duplicate:v1",
        value=material,
    )
    return f"llm-duplicate-v1:{digest}"


def _add_duplicate_marker_best_effort(
    *,
    duplicate_cache: BaseCache,
    duplicate_key: str,
) -> bool | None:
    """Create one content-free marker without making cache outages fatal.

    Args:
        duplicate_cache: Validated cache backend selected by the server.
        duplicate_key: HMAC-only key derived from trusted request context.

    Returns:
        True when created, False when an equivalent marker already exists, or
        None when the cache is temporarily unavailable.
    """
    try:
        return duplicate_cache.add(
            duplicate_key,
            True,
            # The initial lease must outlive the complete provider deadline.
            # The recent-success TTL also provides bounded local-service margin.
            timeout=(
                settings.LLM_TOTAL_TIMEOUT_SECONDS
                + settings.LLM_DUPLICATE_TTL_SECONDS
            ),
        )
    except Exception:
        # PostgreSQL quotas remain the authoritative cost and abuse boundary, so
        # a transient cache outage degrades deduplication instead of availability.
        logger.warning(
            "llm_duplicate_marker operation=add outcome=error request_id=%s",
            get_current_request_id() or "none",
        )
        return None


def _delete_duplicate_marker_best_effort(
    *,
    duplicate_cache: BaseCache,
    duplicate_key: str,
) -> None:
    """Delete a transient marker without masking the primary service failure.

    Args:
        duplicate_cache: Validated cache backend selected by the server.
        duplicate_key: HMAC-only key derived from trusted request context.
    """
    try:
        duplicate_cache.delete(duplicate_key)
    except Exception:
        logger.warning(
            "llm_duplicate_marker operation=delete outcome=error request_id=%s",
            get_current_request_id() or "none",
        )


def _refresh_duplicate_marker_best_effort(
    *,
    duplicate_cache: BaseCache,
    duplicate_key: str,
) -> None:
    """Start the recent-success TTL without risking a valid interpretation.

    Args:
        duplicate_cache: Validated cache backend selected by the server.
        duplicate_key: HMAC-only key derived from trusted request context.
    """
    try:
        # touch() changes only the expiry of the existing content-free marker.
        # It neither stores nor retrieves the message, prompt, or LLM result.
        refreshed = duplicate_cache.touch(
            duplicate_key,
            timeout=settings.LLM_DUPLICATE_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "llm_duplicate_marker operation=touch outcome=error request_id=%s",
            get_current_request_id() or "none",
        )
        return

    if not refreshed:
        # A missing marker weakens only the short duplicate-suppression period;
        # the successful interpretation remains valid and quotas still apply.
        logger.warning(
            "llm_duplicate_marker operation=touch outcome=missing request_id=%s",
            get_current_request_id() or "none",
        )


def interpret_message(
    *,
    user: CustomUser,
    target_message: str,
    previous_context: str = "",
    previous_context_speaker: str = ContextSpeakerRelation.UNKNOWN.value,
    following_context: str = "",
    following_context_speaker: str = ContextSpeakerRelation.UNKNOWN.value,
) -> InterpretationResult:
    """Interpret one transient target using optional surrounding context.

    Args:
        user: Authenticated local user obtained from the Django session.
        target_message: Strictly validated text to interpret, never persisted.
        previous_context: Optional preceding text used only as evidence.
        previous_context_speaker: Previous author's closed relation to the target.
        following_context: Optional subsequent text used only as evidence.
        following_context_speaker: Following author's closed relation to the target.

    Returns:
        Validated interpretation plus deterministic presentation metadata.

    Raises:
        DuplicateInterpretationRequest: If the same request was just submitted.
        InterpretationMessageValidationError: If an internal caller bypasses
            the HTTP boundary with text outside the closed input policy.
        ValueError: If an internal caller supplies invalid author metadata.
        InterpretationOutputRejected: If schema-valid output fails application
            privacy, safety, or semantic business rules.
        LlmQuotaReservationTooLarge: If one provider attempt cannot fit in an
            empty application quota window.
        LlmRateLimitExceeded: If an application quota is exhausted.
        LlmProviderError: If Groq is unavailable or rejects the request.
        LlmProviderResponseError: If provider output is missing, non-JSON, or
            invalid against the strict Pydantic contract.
        InterpretationConfigurationError: If an internal cache, HMAC, or quota
            configuration invariant is invalid.
    """
    normalized_target = validate_and_normalize_interpretation_message(
        target_message,
        max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
    )
    normalized_previous_context = validate_and_normalize_interpretation_message(
        previous_context,
        max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
        allow_blank=True,
    )
    normalized_following_context = validate_and_normalize_interpretation_message(
        following_context,
        max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
        allow_blank=True,
    )
    validated_previous_context_speaker = validate_context_speaker_relation(
        value=previous_context_speaker,
        context=normalized_previous_context,
    )
    validated_following_context_speaker = validate_context_speaker_relation(
        value=following_context_speaker,
        context=normalized_following_context,
    )
    validate_combined_interpretation_length(
        values=(
            normalized_target,
            normalized_previous_context,
            normalized_following_context,
        ),
        max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
    )
    preferences = get_user_preferences(user=user)
    # One request-local registry preserves whether redacted references are equal
    # or distinct without persisting their original values.
    (
        minimized_target,
        minimized_previous_context,
        minimized_following_context,
    ) = minimize_messages_for_provider(
        (
            normalized_target,
            normalized_previous_context,
            normalized_following_context,
        )
    )
    try:
        duplicate_key = _duplicate_cache_key(
            user_id=user.id,
            target_message=normalized_target,
            previous_context=normalized_previous_context,
            previous_context_speaker=validated_previous_context_speaker,
            following_context=normalized_following_context,
            following_context_speaker=validated_following_context_speaker,
            interpretation_detail=preferences.interpretation_detail,
            visual_support_enabled=preferences.visual_support_enabled,
            show_offensive_language=preferences.show_offensive_language,
            show_content_warnings=preferences.show_content_warnings,
        )
        duplicate_cache = get_llm_transient_cache()
    except ImproperlyConfigured as exc:
        _raise_interpretation_configuration_error(cause=exc)
    marker_created = _add_duplicate_marker_best_effort(
        duplicate_cache=duplicate_cache,
        duplicate_key=duplicate_key,
    )

    if marker_created is False:
        raise DuplicateInterpretationRequest(
            "Se ha enviado recientemente una solicitud de interpretación idéntica."
        )

    try:
        messages = build_messages(
            target_message=minimized_target.text,
            previous_context=minimized_previous_context.text,
            previous_context_speaker=validated_previous_context_speaker,
            following_context=minimized_following_context.text,
            following_context_speaker=validated_following_context_speaker,
            preferences=preferences,
        )
        approximate_tokens = estimate_request_tokens(
            messages=messages,
            max_completion_tokens=settings.LLM_MAX_COMPLETION_TOKENS,
        )
        # Reject a permanently impossible token reservation before consuming
        # the authenticated user's logical request quota.
        validate_llm_provider_attempt_capacity(
            estimated_tokens=approximate_tokens,
        )
        reserve_llm_user_request_quota(
            user_id=user.id,
        )
        output = request_interpretation(
            messages=messages,
            approximate_tokens=approximate_tokens,
            # partial binds trusted quota inputs into the no-argument callback
            # invoked immediately before every potential external call.
            attempt_reserver=partial(
                reserve_llm_provider_attempt_quota,
                user_id=user.id,
                estimated_tokens=approximate_tokens,
            ),
        )

        try:
            validated_output = validate_output_business_rules(
                output=output,
                # Concepts and signals belong to the target, never to context.
                analyzed_message=minimized_target.text,
                preferences=preferences,
                max_visual_concepts=settings.LLM_MAX_VISUAL_CONCEPTS,
                max_visual_concept_characters=(
                    settings.LLM_MAX_VISUAL_CONCEPT_CHARACTERS
                ),
            )
            result = InterpretationResult(
                output=validated_output,
                show_content_warning=_should_show_content_warning(
                    output=validated_output,
                    show_content_warnings=preferences.show_content_warnings,
                ),
            )
        except OutputBusinessRuleError as exc:
            logger.warning(
                "llm_interpretation_validation outcome=rejected "
                "error_type=business_rule request_id=%s",
                get_current_request_id() or "none",
            )
            raise InterpretationOutputRejected(
                "La interpretación generada no superó las reglas de seguridad."
            ) from exc
    except ImproperlyConfigured as exc:
        if marker_created is True:
            _delete_duplicate_marker_best_effort(
                duplicate_cache=duplicate_cache,
                duplicate_key=duplicate_key,
            )
        _raise_interpretation_configuration_error(cause=exc)
    except Exception:
        if marker_created is True:
            # Failed calls may be retried by the user. Cache cleanup is best
            # effort and can never replace the original failure.
            _delete_duplicate_marker_best_effort(
                duplicate_cache=duplicate_cache,
                duplicate_key=duplicate_key,
            )
        raise

    if marker_created is True:
        # A successful call receives a complete recent-submission window from
        # this point, rather than only the time left on its initial lease.
        _refresh_duplicate_marker_best_effort(
            duplicate_cache=duplicate_cache,
            duplicate_key=duplicate_key,
        )

    return result
