"""Strict request serializers for interpretation APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, cast

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from .input_validation import (
    CONTEXT_SPEAKER_RELATION_VALUES,
    ContextSpeakerRelation,
    InterpretationMessageValidationError,
    validate_and_normalize_interpretation_message,
    validate_combined_interpretation_length,
    validate_context_speaker_relation,
)


class StrictCharField(serializers.CharField):
    """Reject type coercion before applying DRF string validation."""

    default_error_messages: ClassVar[dict[str, str]] = {
        "invalid": "Se esperaba una cadena de texto.",
    }

    def to_internal_value(self, data: object) -> str:
        """Accept only actual JSON strings.

        Args:
            data: Untrusted JSON field value.

        Returns:
            The validated string.

        Raises:
            ValidationError: If the value is not a string.
        """
        if not isinstance(data, str):
            # Use DRF's field helper to raise ValidationError with the
            # predefined message and stable error code.
            self.fail("invalid")

        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    """Reject string and numeric aliases for JSON booleans."""

    default_error_messages: ClassVar[dict[str, str]] = {
        "invalid": "Se esperaba un valor booleano.",
    }

    def to_internal_value(self, data: object) -> bool:
        """Accept only the JSON true or false primitives.

        Args:
            data: Untrusted JSON field value.

        Returns:
            The validated Boolean.

        Raises:
            ValidationError: If the value is not exactly a Boolean.
        """
        if type(data) is not bool:
            self.fail("invalid")

        return super().to_internal_value(data)


class InterpretationRequestSerializer(serializers.Serializer):
    """Accept one target, optional context, and processing acknowledgment."""

    target_message = StrictCharField(
        min_length=1,
        max_length=settings.LLM_MAX_INPUT_CHARACTERS,
        allow_blank=False,
        trim_whitespace=True,
        write_only=True,
        error_messages={
            "required": "El mensaje es obligatorio.",
            "null": "El mensaje no puede ser nulo.",
            "blank": "El mensaje no puede estar vacío.",
            "min_length": "El mensaje no puede estar vacío.",
            "max_length": (
                "El mensaje no puede superar los "
                f"{settings.LLM_MAX_INPUT_CHARACTERS} caracteres."
            ),
        },
    )
    previous_context = StrictCharField(
        required=False,
        default="",
        allow_blank=True,
        max_length=settings.LLM_MAX_INPUT_CHARACTERS,
        trim_whitespace=True,
        write_only=True,
        error_messages={
            "null": "El contexto anterior no puede ser nulo.",
            "max_length": (
                "El contexto anterior no puede superar los "
                f"{settings.LLM_MAX_INPUT_CHARACTERS} caracteres."
            ),
        },
    )
    previous_context_speaker = serializers.ChoiceField(
        choices=CONTEXT_SPEAKER_RELATION_VALUES,
        required=False,
        default=ContextSpeakerRelation.UNKNOWN.value,
        write_only=True,
        error_messages={
            "invalid_choice": (
                "La relación del autor del contexto anterior no es válida."
            ),
            "null": (
                "La relación del autor del contexto anterior no puede ser nula."
            ),
        },
    )
    following_context = StrictCharField(
        required=False,
        default="",
        allow_blank=True,
        max_length=settings.LLM_MAX_INPUT_CHARACTERS,
        trim_whitespace=True,
        write_only=True,
        error_messages={
            "null": "El contexto posterior no puede ser nulo.",
            "max_length": (
                "El contexto posterior no puede superar los "
                f"{settings.LLM_MAX_INPUT_CHARACTERS} caracteres."
            ),
        },
    )
    following_context_speaker = serializers.ChoiceField(
        choices=CONTEXT_SPEAKER_RELATION_VALUES,
        required=False,
        default=ContextSpeakerRelation.UNKNOWN.value,
        write_only=True,
        error_messages={
            "invalid_choice": (
                "La relación del autor del contexto posterior no es válida."
            ),
            "null": (
                "La relación del autor del contexto posterior no puede ser nula."
            ),
        },
    )
    external_processing_acknowledged = StrictBooleanField(
        write_only=True,
        error_messages={
            "required": (
                "Debes indicar si has confirmado el aviso de "
                "procesamiento externo."
            ),
            "null": (
                "La confirmación del aviso de procesamiento externo "
                "no puede ser nula."
            ),
        },
    )

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Reject non-objects and every unknown client-controlled field.

        Args:
            data: Parsed but untrusted JSON body.

        Returns:
            Strictly validated request values.

        Raises:
            ValidationError: If the body is not an object or has extra fields.
        """
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        ErrorDetail(
                            "Se esperaba un objeto JSON.",
                            code="invalid_json_object",
                        )
                    ]
                }
            )

        unknown_fields = set(data) - set(self.fields)

        if unknown_fields:
            # Do not reflect attacker-controlled field names in the response.
            # One aggregate error also keeps the public contract independent
            # from how many forbidden controls were submitted.
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        ErrorDetail(
                            "La solicitud contiene campos no permitidos.",
                            code="unknown_fields",
                        )
                    ]
                }
            )

        return super().to_internal_value(data)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Normalize every text field and enforce their shared total limit.

        Args:
            attrs: Strictly typed values accepted by the serializer fields.

        Returns:
            Canonical target and context values plus the acknowledgment.

        Raises:
            ValidationError: If any text violates the closed input policy or
                their combined length exceeds the server-owned maximum.
        """
        text_fields = (
            ("target_message", False),
            ("previous_context", True),
            ("following_context", True),
        )
        normalized_values: list[str] = []

        for field_name, allow_blank in text_fields:
            try:
                # StrictCharField already guarantees the runtime type; cast()
                # communicates that closed boundary to static analysis only.
                normalized_value = validate_and_normalize_interpretation_message(
                    cast(str, attrs[field_name]),
                    max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
                    allow_blank=allow_blank,
                )
            except InterpretationMessageValidationError as exc:
                # Attach the shared domain code to the responsible HTTP field.
                raise serializers.ValidationError(
                    {
                        field_name: [
                            ErrorDetail(str(exc), code=exc.code)
                        ]
                    }
                ) from exc

            attrs[field_name] = normalized_value
            normalized_values.append(normalized_value)

        try:
            validate_combined_interpretation_length(
                values=tuple(normalized_values),
                max_characters=settings.LLM_MAX_INPUT_CHARACTERS,
            )
        except InterpretationMessageValidationError as exc:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        ErrorDetail(str(exc), code=exc.code)
                    ]
                }
            ) from exc

        for context_field, speaker_field in (
            ("previous_context", "previous_context_speaker"),
            ("following_context", "following_context_speaker"),
        ):
            try:
                relation = validate_context_speaker_relation(
                    value=attrs[speaker_field],
                    context=cast(str, attrs[context_field]),
                )
            except ValueError as exc:
                # A non-empty author relation cannot describe missing context.
                raise serializers.ValidationError(
                    {
                        speaker_field: [
                            ErrorDetail(
                                str(exc),
                                code="context_speaker_without_context",
                            )
                        ]
                    }
                ) from exc

            attrs[speaker_field] = relation.value

        return attrs

    def validate_external_processing_acknowledged(self, value: bool) -> bool:
        """Require acknowledgment before transient processing by Groq.

        Args:
            value: Strict JSON Boolean supplied after the user-facing notice.

        Returns:
            True when external processing has been acknowledged.

        Raises:
            ValidationError: If acknowledgment is false.
        """
        if value is not True:
            raise serializers.ValidationError(
                (
                    "Debes confirmar que has sido informado del procesamiento "
                    "externo para continuar."
                ),
                code="external_processing_not_acknowledged",
            )

        return value
