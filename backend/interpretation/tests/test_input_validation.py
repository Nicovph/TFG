"""Focused tests for the reusable interpretation message policy."""

from django.test import SimpleTestCase

from ..input_validation import (
    InterpretationMessageValidationError,
    validate_and_normalize_interpretation_message,
    validate_combined_interpretation_length,
)


class InterpretationMessagePolicyTests(SimpleTestCase):
    """Verify canonicalization and Unicode controls at their owning layer."""

    def test_normalizes_compatible_unicode_line_endings_and_whitespace(
        self,
    ) -> None:
        """Produce one canonical representation across clients."""
        normalized = validate_and_normalize_interpretation_message(
            "  Ｈｏｌａ， amigo.\r\nSegunda.\rTercera.  ",
            max_characters=500,
        )

        self.assertEqual(
            normalized,
            "Hola, amigo.\nSegunda.\nTercera.",
        )

    def test_rejects_empty_or_excessive_text_after_normalization(self) -> None:
        """Apply blank and length checks to the canonical value."""
        cases = (
            ("  \r\n  ", 500, "blank_after_normalization"),
            ("\ufdfa" * 30, 500, "max_length_after_normalization"),
        )

        for message, limit, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(
                    InterpretationMessageValidationError
                ) as raised:
                    validate_and_normalize_interpretation_message(
                        message,
                        max_characters=limit,
                    )

                self.assertEqual(raised.exception.code, expected_code)

    def test_accepts_zwj_only_between_emoji_compatible_components(self) -> None:
        """Preserve meaningful emoji while rejecting hidden separators."""
        accepted_messages = (
            "Mi familia es 👨‍👩‍👧.",
            "La médica respondió 👩‍⚕️.",
            "Estoy trabajando 🧑🏽‍💻.",
        )
        rejected_messages = (
            "Llama al 612\u200d345678.",
            "Escribe a usuario\u200d@example.com.",
            "Texto con\u200cseparador.",
            "Texto con dirección \u202ecambiada.",
        )

        for message in accepted_messages:
            with self.subTest(message=message):
                self.assertEqual(
                    validate_and_normalize_interpretation_message(
                        message,
                        max_characters=500,
                    ),
                    message,
                )

        for message in rejected_messages:
            with self.subTest(message=message):
                with self.assertRaises(
                    InterpretationMessageValidationError
                ) as raised:
                    validate_and_normalize_interpretation_message(
                        message,
                        max_characters=500,
                    )

                self.assertEqual(
                    raised.exception.code,
                    "disallowed_control_or_format_characters",
                )

    def test_rejects_invalid_internal_type_and_server_limit(self) -> None:
        """Fail closed when an internal caller bypasses the HTTP serializer."""
        with self.assertRaises(InterpretationMessageValidationError) as raised:
            validate_and_normalize_interpretation_message(
                123,  # type: ignore[arg-type]
                max_characters=500,
            )

        self.assertEqual(raised.exception.code, "invalid_message_type")

        with self.assertRaisesMessage(
            ValueError,
            "El límite máximo de caracteres del mensaje debe ser positivo.",
        ):
            validate_and_normalize_interpretation_message(
                "Mensaje sintético.",
                max_characters=0,
            )

    def test_optional_blank_and_combined_length_policy(self) -> None:
        """Canonicalize absent context and bound all transient text together."""
        self.assertEqual(
            validate_and_normalize_interpretation_message(
                " \r\n ",
                max_characters=5,
                allow_blank=True,
            ),
            "",
        )
        validate_combined_interpretation_length(
            values=("ab", "cd", "e"),
            max_characters=5,
        )

        with self.assertRaises(
            InterpretationMessageValidationError
        ) as raised:
            validate_combined_interpretation_length(
                values=("ab", "cd", "ef"),
                max_characters=5,
            )

        self.assertEqual(raised.exception.code, "max_total_length")
