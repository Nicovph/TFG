"""Closed Pydantic contracts for untrusted LLM structured output."""

from __future__ import annotations

import re
import unicodedata

# Annotated allows adding validation metadata to a base type.
# Literal allows the declaration of closed sets of values.
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.preferences.models import UserPreferences

from .limits import (
    INTERPRETATION_CHARACTER_LIMITS,
    MAX_INTERPRETATION_CHARACTERS,
)
from .privacy import (
    IdentifierCategory,
    detect_output_identifier_candidates,
)


# Strict strings reject coercion and remove only leading and trailing whitespace.
StrictText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True)]
SignalKind = Literal[
    "possible_irony",
    "possible_ambiguity",
    "possible_indirect_language",
    "possible_offensive_language",
    "possible_aggression",
    "possible_cyberbullying",
]

# Each component contains Unicode alphanumeric characters but no underscore.
# ASCII hyphens may join components, and spaces may separate at most three words.
CONCEPT_PATTERN = re.compile(
    r"[^\W_]+(?:-[^\W_]+)*(?: [^\W_]+(?:-[^\W_]+)*){0,2}"
)

# This pattern is a rejection rule, not an HTML or URI sanitizer.
# The fourth: the protocol-relative rule excludes slash pairs preceded by a colon so it
# does not duplicate the protocol separator in an already matched URI.
DISALLOWED_OUTPUT_PATTERN = re.compile(
    r"(?:"
    r"https?://|"
    r"www\.|"
    r"(?<!:)//[^\s<>]+|"
    r"(?:javascript|data|file|ftp|mailto|blob|tel):|"
    r"<[^>]+>|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r")",
    flags=re.IGNORECASE,
)
COMPARISON_TOKEN_PATTERN = re.compile(r"[^\W_]+")

class PragmaticSignal(BaseModel):
    """Represent one closed pragmatic signal without diagnostic claims."""

    # Reject unknown fields such as a provider-generated confidence property.
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: SignalKind = Field(
        description=(
            "Tipo cerrado de señal pragmática posible respaldada por el mensaje."
        )
    )
    explanation: Annotated[
        StrictText,
        StringConstraints(min_length=1, max_length=240),
        Field(
            description=(
                "Justificación breve y cauta de la señal, sin afirmar "
                "intenciones como ciertas."
            )
        ),
    ]


class LLMInterpretationOutput(BaseModel):
    """Represent the only provider response shape accepted by the backend."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["pragmatic_interpretation"] = Field(
        description="Discriminador fijo del contrato de interpretación."
    )
    interpretation: Annotated[
        StrictText,
        StringConstraints(
            min_length=1,
            max_length=MAX_INTERPRETATION_CHARACTERS,
        ),
        Field(
            description=(
                "Explicación del significado pragmático, sus posibles lecturas "
                "y la incertidumbre relevante."
            )
        ),
    ]
    clear_reformulation: Annotated[
        StrictText,
        StringConstraints(min_length=1, max_length=700),
        Field(
            description=(
                "Versión directa y literal del mensaje sin análisis adicional."
            )
        ),
    ]
    needs_more_context: bool = Field(
        description=(
            "Indica si falta información relevante para interpretar el mensaje."
        )
    )
    context_note: Annotated[
        StrictText,
        StringConstraints(min_length=0, max_length=300),
        Field(
            description=(
                "Describe únicamente el contexto que falta y queda vacío "
                "cuando no se necesita más contexto."
            )
        ),
    ]
    signals: list[PragmaticSignal] = Field(
        max_length=6,
        description=(
            "Señales posibles respaldadas por el mensaje, sin tipos duplicados."
        ),
    )
    visual_concepts: list[
        Annotated[StrictText, StringConstraints(min_length=1, max_length=64)]
    ] = Field(
        max_length=10,
        description=(
            "Conceptos genéricos y atómicos para búsqueda visual en ARASAAC."
        ),
    )


class OutputBusinessRuleError(ValueError):
    """Indicate that schema-valid output violates application rules."""


def _normalize_unicode(value: str) -> str:
    """Return the canonical Unicode representation used by the backend.

    Args:
        value: Text to normalize without storing it.

    Returns:
        The NFKC-normalized Unicode string.
    """
    return unicodedata.normalize("NFKC", value)


def _tokenize_for_lexical_comparison(value: str) -> tuple[str, ...]:
    """Normalize text into tokens for duplicate and disclosure comparisons.

    Args:
        value: Text to compare without storing it.

    Returns:
        Case-folded Unicode alphanumeric tokens without punctuation.
    """
    normalized = _normalize_unicode(value).casefold()
    return tuple(COMPARISON_TOKEN_PATTERN.findall(normalized))


def _reject_output_identifier_candidates(value: str) -> None:
    """Reject identifier candidates found in one untrusted output field.

    Args:
        value: Schema-valid provider text held only in process memory.

    Raises:
        OutputBusinessRuleError: If a forbidden identifier candidate is found.
    """
    detected = detect_output_identifier_candidates(value)

    if IdentifierCategory.LONG_NUMERIC_CANDIDATE in detected:
        raise OutputBusinessRuleError(
            "La salida contiene un candidato a identificador numérico largo."
        )

    if detected:
        raise OutputBusinessRuleError(
            "La salida contiene un posible identificador personal."
        )


def validate_output_business_rules(
    *,
    output: LLMInterpretationOutput,
    analyzed_message: str,
    preferences: UserPreferences,
    max_visual_concepts: int,
    max_visual_concept_characters: int,
) -> LLMInterpretationOutput:
    """Apply semantic limits after strict Pydantic validation.

    Args:
        output: Schema-valid provider output.
        analyzed_message: Locally minimized message sent to the provider.
        preferences: Server-owned interpretation preferences for the user.
        max_visual_concepts: Maximum concepts allowed by backend configuration.
        max_visual_concept_characters: Maximum characters in each concept.

    Returns:
        A validated output whose visual concepts use canonical Unicode.

    Raises:
        OutputBusinessRuleError: If output contains disallowed data, exceeds
            configured limits, contains duplicates, is inconsistent, or
            lexically reproduces the analyzed message.
    """
    detail_limit = INTERPRETATION_CHARACTER_LIMITS[
        preferences.interpretation_detail
    ]

    if len(output.interpretation) > detail_limit:
        raise OutputBusinessRuleError(
            "La interpretación supera el nivel de detalle seleccionado."
        )

    # The expression with * expands each signal explanation within the tuple.
    text_fields = (
        output.interpretation,
        output.clear_reformulation,
        output.context_note,
        *(signal.explanation for signal in output.signals),
    )

    if any(DISALLOWED_OUTPUT_PATTERN.search(value) for value in text_fields):
        raise OutputBusinessRuleError(
            "La salida contiene una URL, una dirección de correo electrónico, "
            "un esquema URI o marcado no permitidos."
        )

    for value in text_fields:
        _reject_output_identifier_candidates(value)

    if output.needs_more_context != bool(output.context_note):
        raise OutputBusinessRuleError(
            "Los campos de contexto son incoherentes."
        )

    signal_kinds = [signal.kind for signal in output.signals]

    # Each closed signal kind may occur at most once.
    if len(signal_kinds) != len(set(signal_kinds)):
        raise OutputBusinessRuleError(
            "Los tipos de señales deben ser únicos."
        )

    if not preferences.visual_support_enabled and output.visual_concepts:
        raise OutputBusinessRuleError(
            "Los conceptos visuales están desactivados."
        )

    if len(output.visual_concepts) > max_visual_concepts:
        raise OutputBusinessRuleError(
            "La salida contiene demasiados conceptos visuales."
        )

    canonical_concepts: list[str] = []
    normalized_concept_tokens: list[tuple[str, ...]] = []

    for concept in output.visual_concepts:
        canonical_concept = _normalize_unicode(concept)

        if len(canonical_concept) > max_visual_concept_characters:
            raise OutputBusinessRuleError(
                "Un concepto visual es demasiado largo."
            )

        _reject_output_identifier_candidates(canonical_concept)

        if not CONCEPT_PATTERN.fullmatch(canonical_concept):
            raise OutputBusinessRuleError(
                "Un concepto visual no es atómico."
            )

        concept_tokens = _tokenize_for_lexical_comparison(canonical_concept)

        if concept_tokens in normalized_concept_tokens:
            raise OutputBusinessRuleError(
                "Los conceptos visuales deben ser únicos."
            )

        canonical_concepts.append(canonical_concept)
        normalized_concept_tokens.append(concept_tokens)

    normalized_message_tokens = _tokenize_for_lexical_comparison(analyzed_message)
    flattened_concept_tokens = tuple(
        token
        for concept_tokens in normalized_concept_tokens
        for token in concept_tokens
    )

    if (
        flattened_concept_tokens
        and flattened_concept_tokens == normalized_message_tokens
    ):
        raise OutputBusinessRuleError(
            "Los conceptos visuales reproducen el mensaje."
        )

    # Serializes the entire instance to a native Python dictionary
    # containing all model fields with their current values.
    canonical_payload = output.model_dump()
    canonical_payload["visual_concepts"] = canonical_concepts
    # Re-run the closed schema after inserting the canonical concept values.
    return LLMInterpretationOutput.model_validate(canonical_payload)
