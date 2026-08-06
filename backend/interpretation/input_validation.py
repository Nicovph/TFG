"""Pure validation policy for transient interpretation messages."""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Final

from .privacy import normalize_message_text


class ContextSpeakerRelation(StrEnum):
    """Represent one context author's relation to the target author."""

    SAME_AS_TARGET_AUTHOR = "same_as_target_author"
    DIFFERENT_FROM_TARGET_AUTHOR = "different_from_target_author"
    UNKNOWN = "unknown"


CONTEXT_SPEAKER_RELATION_VALUES: Final[tuple[str, ...]] = tuple(
    relation.value for relation in ContextSpeakerRelation
)


# Unicode Cc controls are rejected except for LF and TAB, which are required
# for ordinary multiline messages.
_ALLOWED_CONTROL_CHARACTERS: Final[frozenset[str]] = frozenset(
    {
        "\n",
        "\t",
    }
)
# U+200D is the only Unicode Cf format character considered for admission, and
# it is still accepted only when `_is_contextual_emoji_joiner` approves it.
_ZERO_WIDTH_JOINER: Final = "\u200d"
# FE0E selects text presentation and FE0F selects emoji presentation. They are
# skipped only while finding the visible components around a candidate ZWJ.
_EMOJI_VARIATION_SELECTORS: Final[frozenset[str]] = frozenset(
    {
        "\ufe0e",
        "\ufe0f",
    }
)
# So covers ordinary symbols, Sk includes emoji skin-tone modifiers, and Sm is
# needed by directional emoji that contain arrow-like mathematical symbols.
_EMOJI_COMPONENT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "So",
        "Sk",
        "Sm",
    }
)


class InterpretationMessageValidationError(ValueError):
    """Represent one closed message-policy failure independently of DRF."""

    def __init__(self, message: str, *, code: str) -> None:
        """Store a Spanish message and stable internal validation code.

        Args:
            message: Human-readable Spanish validation failure.
            code: Stable closed code suitable for API error mapping.
        """
        super().__init__(message)
        self.code = code


def validate_context_speaker_relation(
    *,
    value: object,
    context: str,
) -> ContextSpeakerRelation:
    """Validate closed author metadata against its optional context.

    Args:
        value: Untrusted or internally supplied relation value.
        context: Canonical context text governed by the relation.

    Returns:
        The validated closed relation.

    Raises:
        ValueError: If the relation is unknown or attributes absent context.
    """
    if not isinstance(value, str):
        raise ValueError(
            "La relación del autor del contexto no es válida."
        )

    try:
        relation = ContextSpeakerRelation(value)
    except ValueError as exc:
        raise ValueError(
            "La relación del autor del contexto no es válida."
        ) from exc

    if not context and relation is not ContextSpeakerRelation.UNKNOWN:
        raise ValueError(
            "No se puede indicar el autor de un contexto vacío."
        )

    return relation


def _adjacent_emoji_component_category(
    *,
    value: str,
    joiner_index: int,
    step: int,
) -> str | None:
    """Find one emoji-compatible component next to a joiner.

    Args:
        value: Canonical message containing the candidate joiner.
        joiner_index: Index of the ZERO WIDTH JOINER under inspection.
        step: Search direction, using -1 for the left or 1 for the right.

    Returns:
        The Unicode category of the adjacent emoji-compatible component, or
        None when the neighboring character cannot form the permitted context.
    """
    candidate_index = joiner_index + step

    # Text and emoji variation selectors refine presentation and may appear
    # between the visible symbol and the ZWJ.
    while (
        0 <= candidate_index < len(value)
        and value[candidate_index] in _EMOJI_VARIATION_SELECTORS
    ):
        candidate_index += step

    if not 0 <= candidate_index < len(value):
        return None

    category = unicodedata.category(value[candidate_index])

    if category not in _EMOJI_COMPONENT_CATEGORIES:
        return None

    return category


def _is_contextual_emoji_joiner(
    *,
    value: str,
    joiner_index: int,
) -> bool:
    """Allow ZWJ only between components compatible with an emoji sequence.

    Args:
        value: Canonical message containing the candidate joiner.
        joiner_index: Index of the ZERO WIDTH JOINER under inspection.

    Returns:
        True when both sides are symbol-like and at least one is an ordinary
        Unicode symbol, preventing use inside words or numeric identifiers.
    """
    left_category = _adjacent_emoji_component_category(
        value=value,
        joiner_index=joiner_index,
        step=-1,
    )
    right_category = _adjacent_emoji_component_category(
        value=value,
        joiner_index=joiner_index,
        step=1,
    )

    if left_category is None or right_category is None:
        return False

    # Require at least one ordinary symbol so the ZWJ sits in a real emoji
    # sequence rather than acting as a hidden separator.
    return "So" in {left_category, right_category}


def _contains_disallowed_control_or_format(value: str) -> bool:
    """Detect control or format characters outside the narrow input policy.

    Args:
        value: Canonical message to inspect before trusted processing.

    Returns:
        True when the message contains a prohibited Unicode character.
    """
    for index, character in enumerate(value):
        category = unicodedata.category(character)

        # Cc contains control characters. Only LF and TAB are needed for
        # ordinary multiline messages; terminal and other controls are rejected.
        if (
            category == "Cc"
            and character not in _ALLOWED_CONTROL_CHARACTERS
        ):
            return True

        if category != "Cf":
            continue

        # Cf contains invisible formatting controls. ZWJ is permitted only
        # between emoji-compatible symbols so composed emojis keep their
        # pragmatic meaning. ZWNJ and bidirectional controls remain rejected.
        if (
            character == _ZERO_WIDTH_JOINER
            and _is_contextual_emoji_joiner(
                value=value,
                joiner_index=index,
            )
        ):
            continue

        return True

    return False


def validate_and_normalize_interpretation_message(
    value: str,
    *,
    max_characters: int,
    allow_blank: bool = False,
) -> str:
    """Return canonical text that satisfies the shared input policy.

    Args:
        value: Text received at an HTTP or internal service boundary.
        max_characters: Positive server-owned limit applied after normalization.
        allow_blank: Whether an absent optional context may normalize to empty.

    Returns:
        NFKC-normalized, LF-only text without outer whitespace.

    Raises:
        InterpretationMessageValidationError: If the type, content, or length is
            outside the closed message policy.
        ValueError: If the server-owned maximum is not positive.
    """
    if max_characters < 1:
        raise ValueError(
            "El límite máximo de caracteres del mensaje debe ser positivo."
        )

    if not isinstance(value, str):
        raise InterpretationMessageValidationError(
            "Se esperaba una cadena de texto.",
            code="invalid_message_type",
        )

    # Convert Windows CRLF and legacy CR endings to the single LF form used
    # internally so equivalent multiline input is processed consistently.
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalize_message_text(normalized)
    normalized = normalized.strip()

    if not normalized and not allow_blank:
        raise InterpretationMessageValidationError(
            "El mensaje no puede estar vacío.",
            code="blank_after_normalization",
        )

    if len(normalized) > max_characters:
        raise InterpretationMessageValidationError(
            f"El mensaje no puede superar los {max_characters} caracteres.",
            code="max_length_after_normalization",
        )

    if _contains_disallowed_control_or_format(normalized):
        raise InterpretationMessageValidationError(
            "El mensaje contiene caracteres de control o formato no permitidos.",
            code="disallowed_control_or_format_characters",
        )

    return normalized


def validate_combined_interpretation_length(
    *,
    values: tuple[str, ...],
    max_characters: int,
) -> None:
    """Enforce one data-minimising limit across target and context text.

    Args:
        values: Canonical target message and optional context values.
        max_characters: Positive server-owned combined character limit.

    Raises:
        InterpretationMessageValidationError: If the combined text is too long.
        ValueError: If the server-owned maximum is not positive.
    """
    if max_characters < 1:
        raise ValueError(
            "El límite máximo combinado de caracteres debe ser positivo."
        )

    if sum(len(value) for value in values) > max_characters:
        raise InterpretationMessageValidationError(
            (
                "El mensaje y sus contextos no pueden superar en conjunto "
                f"los {max_characters} caracteres."
            ),
            code="max_total_length",
        )
