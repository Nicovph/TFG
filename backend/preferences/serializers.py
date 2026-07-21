"""Strict API serializers for authenticated user preferences, to define 
and protect the API input and output contract, including representation, 
normalization, and validation."""

from collections.abc import Mapping
from typing import Any

from rest_framework import serializers

from .models import InterpretationDetail, Theme, UserPreferences


class StrictBooleanField(serializers.BooleanField):
    """Accept JSON boolean primitives without permissive string coercion."""

    def to_internal_value(self, data: Any) -> bool:
        """Validate that the untrusted value is exactly a JSON boolean.

        Args:
            data: The raw field value received from the request payload.

        Returns:
            The validated boolean value.

        Raises:
            ValidationError: If the value is not a boolean primitive.
        """
        if not isinstance(data, bool):
            # Raise ValidationError using DRF's error message system.
            self.fail("invalid", input=data)

        return data


class UserPreferencesSerializer(serializers.Serializer):
    """Validate and expose the minimal persisted preference contract."""

    visual_support_enabled = StrictBooleanField()
    show_offensive_language = StrictBooleanField()
    show_content_warnings = StrictBooleanField()
    theme = serializers.ChoiceField(choices=Theme.values)
    interpretation_detail = serializers.ChoiceField(
        choices=InterpretationDetail.values,
    )

    def to_internal_value(self, data: Any) -> dict[str, object]:
        """Reject non-object payloads and fields outside the closed contract.

        Args:
            data: The untrusted request payload received by Django REST Framework.

        Returns:
            Validated primitive preference values.

        Raises:
            ValidationError: If the payload is not an object or contains an
                unsupported field.
        """
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                # A list is used, because there could be more than one error messages.
                {"non_field_errors": ["Se esperaba un objeto JSON."]},
            )

        unknown_fields = set(data) - set(self.fields)

        if unknown_fields:
            raise serializers.ValidationError(
                # Uses dict comprehension to map each invalid field to a clear error.
                # Example: {"email": ["Campo no permitido."], "status": ["Campo no permitido."]}
                {
                    field_name: ["Campo no permitido."]
                    for field_name in sorted(unknown_fields)
                },
            )

        # After custom validation, delegate to parent class (UserPreferencesSerializer) 
        # to run standard field validation and value conversion.
        return super().to_internal_value(data)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require each update request to contain at least one preference.

        Args:
            attrs: Preference values already validated by individual fields.

        Returns:
            The validated non-empty preference mapping.

        Raises:
            ValidationError: If a partial update contains no preference values.
        """
        # partial allows the validation of the preferences included in a PATCH.
        if self.partial and not attrs:
            raise serializers.ValidationError(
                "Se requiere al menos una preferencia.",
            )

        return attrs

    def to_representation(self, instance: UserPreferences) -> dict[str, object]:
        """Serialize only the five values needed by the application.

        Args:
            instance: The authenticated user's preference record.

        Returns:
            A minimal dictionary without identifiers or timestamps.
        """
        return super().to_representation(instance)
