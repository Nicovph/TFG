"""Focused tests for the closed interpretation request serializer."""

from django.conf import settings
from django.test import SimpleTestCase

from ..input_validation import ContextSpeakerRelation
from ..serializers import InterpretationRequestSerializer


class InterpretationRequestSerializerTests(SimpleTestCase):
    """Verify input privacy, canonicalization, and closed validation errors."""

    def _build_payload(self, *, target_message: str) -> dict[str, object]:
        """Build one minimal valid request payload with synthetic text.

        Args:
            target_message: Synthetic target message under test.

        Returns:
            A closed request payload with the external-processing notice
            acknowledged.
        """
        return {
            "target_message": target_message,
            "external_processing_acknowledged": True,
        }

    def test_input_fields_are_validated_but_never_represented(self) -> None:
        """Keep accepted request content out of serializer output.

        Args:
            self: The test case instance.
        """
        serializer = InterpretationRequestSerializer(
            data=self._build_payload(target_message="Cierra la ventana."),
        )

        self.assertEqual(
            set(serializer.fields),
            {
                "target_message",
                "previous_context",
                "previous_context_speaker",
                "following_context",
                "following_context_speaker",
                "external_processing_acknowledged",
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data,
            {
                "target_message": "Cierra la ventana.",
                "previous_context": "",
                "previous_context_speaker": "unknown",
                "following_context": "",
                "following_context_speaker": "unknown",
                "external_processing_acknowledged": True,
            },
        )
        self.assertEqual(serializer.data, {})

    def test_context_speaker_relations_are_closed_and_require_context(
        self,
    ) -> None:
        """Reject unknown relations and attribution without context text."""
        cases = (
            (
                {
                    **self._build_payload(target_message="Mensaje objetivo."),
                    "previous_context": "Mensaje anterior.",
                    "previous_context_speaker": "persona_a",
                },
                "previous_context_speaker",
                "invalid_choice",
            ),
            (
                {
                    **self._build_payload(target_message="Mensaje objetivo."),
                    "following_context_speaker": (
                        ContextSpeakerRelation.SAME_AS_TARGET_AUTHOR.value
                    ),
                },
                "following_context_speaker",
                "context_speaker_without_context",
            ),
        )

        for payload, field_name, error_code in cases:
            with self.subTest(field_name=field_name, error_code=error_code):
                serializer = InterpretationRequestSerializer(data=payload)

                self.assertFalse(serializer.is_valid())
                self.assertEqual(
                    serializer.errors[field_name][0].code,
                    error_code,
                )

    def test_maps_the_shared_message_policy_error_code(self) -> None:
        """Preserve one representative domain error at the DRF boundary."""
        serializer = InterpretationRequestSerializer(
            data={
                **self._build_payload(target_message="Texto visible."),
                "previous_context": "Texto con dirección \u202ecambiada.",
            },
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["previous_context"][0].code,
            "disallowed_control_or_format_characters",
        )

    def test_closed_request_failures_expose_stable_internal_codes(self) -> None:
        """Expose codes consumed by the stable HTTP error representation.

        Args:
            self: The test case instance.
        """
        false_acknowledgment = InterpretationRequestSerializer(
            data={
                "target_message": "Hola.",
                "external_processing_acknowledged": False,
            },
        )
        unknown_field = InterpretationRequestSerializer(
            data={
                **self._build_payload(target_message="Hola."),
                "model": "client-controlled",
            },
        )
        non_object = InterpretationRequestSerializer(data=["Hola."])

        self.assertFalse(false_acknowledgment.is_valid())
        self.assertFalse(unknown_field.is_valid())
        self.assertFalse(non_object.is_valid())
        self.assertEqual(
            false_acknowledgment.errors[
                "external_processing_acknowledged"
            ][0].code,
            "external_processing_not_acknowledged",
        )
        self.assertEqual(
            unknown_field.errors["non_field_errors"][0].code,
            "unknown_fields",
        )
        self.assertNotIn("model", str(unknown_field.errors))
        self.assertEqual(
            non_object.errors["non_field_errors"][0].code,
            "invalid_json_object",
        )

    def test_strict_fields_reject_json_type_coercion(self) -> None:
        """Reject non-string text fields and non-Boolean aliases.

        Args:
            self: The test case instance.
        """
        cases = (
            (
                {
                    "target_message": 123,
                    "external_processing_acknowledged": True,
                },
                "target_message",
            ),
            (
                {
                    "target_message": "Hola.",
                    "previous_context": 123,
                    "external_processing_acknowledged": True,
                },
                "previous_context",
            ),
            (
                {
                    "target_message": "Hola.",
                    "following_context": False,
                    "external_processing_acknowledged": True,
                },
                "following_context",
            ),
            (
                {
                    "target_message": "Hola.",
                    "external_processing_acknowledged": "true",
                },
                "external_processing_acknowledged",
            ),
            (
                {
                    "target_message": "Hola.",
                    "external_processing_acknowledged": 1,
                },
                "external_processing_acknowledged",
            ),
        )

        for payload, field_name in cases:
            with self.subTest(field_name=field_name, value=payload[field_name]):
                serializer = InterpretationRequestSerializer(data=payload)

                self.assertFalse(serializer.is_valid())
                self.assertEqual(
                    serializer.errors[field_name][0].code,
                    "invalid",
                )

    def test_rejects_text_above_the_serializer_input_limit(self) -> None:
        """Enforce the pre-normalization length boundary in DRF.

        Args:
            self: The test case instance.
        """
        serializer = InterpretationRequestSerializer(
            data=self._build_payload(
                target_message=(
                    "x" * (settings.LLM_MAX_INPUT_CHARACTERS + 1)
                ),
            ),
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["target_message"][0].code,
            "max_length",
        )

    def test_normalizes_context_and_enforces_combined_input_limit(self) -> None:
        """Accept the exact total boundary and reject one extra character."""
        target_length = settings.LLM_MAX_INPUT_CHARACTERS // 2
        previous_length = settings.LLM_MAX_INPUT_CHARACTERS - target_length
        exact_payload = {
            **self._build_payload(target_message="x" * target_length),
            "previous_context": "ｙ" * previous_length,
            "following_context": "  ",
        }
        exact = InterpretationRequestSerializer(data=exact_payload)

        self.assertTrue(exact.is_valid(), exact.errors)
        self.assertEqual(
            exact.validated_data["previous_context"],
            "y" * previous_length,
        )
        self.assertEqual(exact.validated_data["following_context"], "")

        excessive = InterpretationRequestSerializer(
            data={**exact_payload, "following_context": "z"},
        )

        self.assertFalse(excessive.is_valid())
        self.assertEqual(
            excessive.errors["non_field_errors"][0].code,
            "max_total_length",
        )
