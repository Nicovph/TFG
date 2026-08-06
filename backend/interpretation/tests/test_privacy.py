"""Focused tests for transient identifier minimisation and output detection."""

from django.test import SimpleTestCase

from ..privacy import (
    IdentifierCategory,
    detect_output_identifier_candidates,
    minimize_message_for_provider,
    minimize_messages_for_provider,
)


class InputMinimisationTests(SimpleTestCase):
    """Verify conservative provider-bound minimisation without persistence."""

    def test_distinct_values_receive_stable_numbered_placeholders(self) -> None:
        """Preserve cross-field references without retaining matched values."""
        target, previous, following = minimize_messages_for_provider(
            (
                "Escribe a ana@example.org.",
                "Antes hablaste con ana@example.org.",
                "Mejor responde a bea@example.org.",
            )
        )

        self.assertEqual(
            (target.text, previous.text, following.text),
            (
                "Escribe a [EMAIL_1].",
                "Antes hablaste con [EMAIL_1].",
                "Mejor responde a [EMAIL_2].",
            ),
        )
        self.assertEqual(
            (
                target.detected_categories,
                previous.detected_categories,
                following.detected_categories,
            ),
            (frozenset({IdentifierCategory.EMAIL}),) * 3,
        )

    def test_ipv4_candidates_cover_punctuation_and_leading_zeroes(self) -> None:
        """Redact conservative IPv4 forms without partial dotted matches."""
        punctuated = minimize_message_for_provider(
            "Mi IP es 192.168.1.1."
        )
        leading_zeroes = minimize_message_for_provider(
            "Mi IP es 192.168.001.001."
        )
        invalid_five_part = minimize_message_for_provider(
            "La versión es 1.2.3.4.5."
        )

        self.assertEqual(punctuated.text, "Mi IP es [IP_1].")
        self.assertEqual(leading_zeroes.text, "Mi IP es [IP_1].")
        self.assertEqual(
            invalid_five_part.text,
            "La versión es 1.2.3.4.5.",
        )
        self.assertFalse(invalid_five_part.detected_categories)

    def test_ipv6_candidates_cover_common_valid_forms(self) -> None:
        """Redact compressed, bracketed, and embedded-IPv4 IPv6 addresses."""
        samples = (
            ("IP 2001:db8::1.", "IP [IP_1]."),
            ("IP [2001:db8::1].", "IP [IP_1]."),
            ("IP 2001:db8:0:0:0:0:2:1.", "IP [IP_1]."),
            ("IP ::ffff:192.0.2.128.", "IP [IP_1]."),
        )

        for source, expected in samples:
            with self.subTest(source=source):
                minimized = minimize_message_for_provider(source)
                self.assertEqual(minimized.text, expected)
                self.assertIn(
                    IdentifierCategory.IP_ADDRESS_CANDIDATE,
                    minimized.detected_categories,
                )

        ordinary_time = minimize_message_for_provider("La hora es 12:30.")
        self.assertEqual(ordinary_time.text, "La hora es 12:30.")
        self.assertFalse(ordinary_time.detected_categories)

    def test_url_replacement_preserves_sentence_punctuation(self) -> None:
        """Keep closing punctuation that is not part of the URL candidate."""
        minimized = minimize_message_for_provider(
            "Visita https://example.org/path)."
        )

        self.assertEqual(minimized.text, "Visita [URL_1]).")
        self.assertEqual(
            minimized.detected_categories,
            frozenset({IdentifierCategory.URL}),
        )

    def test_unicode_normalization_improves_candidate_detection(self) -> None:
        """Detect compatibility digits and internationalized email domains."""
        fullwidth_phone = minimize_message_for_provider(
            "Llama al ００３４ ６１２３４５６７８."
        )
        unicode_email = minimize_message_for_provider(
            "Escribe a usuario@ejemplo.рф."
        )
        punycode_email = minimize_message_for_provider(
            "Escribe a usuario@xn--e1afmkfd.xn--p1ai."
        )

        self.assertEqual(fullwidth_phone.text, "Llama al [TELEFONO_1].")
        self.assertEqual(unicode_email.text, "Escribe a [EMAIL_1].")
        self.assertEqual(punycode_email.text, "Escribe a [EMAIL_1].")

    def test_spanish_document_and_iban_rules_validate_shape_not_checksum(
        self,
    ) -> None:
        """Redact plausible Spanish forms whether their checksum is valid or not."""
        minimized = minimize_message_for_provider(
            "DNI 12345678Z y 12345678A; NIE X1234567L y X1234567A; IBAN "
            "ES91 2100 0418 4502 0005 1332 y "
            "ES00 0000 0000 0000 0000 0000."
        )

        self.assertEqual(
            minimized.text,
            "DNI [DOCUMENTO_1] y [DOCUMENTO_2]; NIE "
            "[DOCUMENTO_3] y [DOCUMENTO_4]; IBAN "
            "[IBAN_1] y [IBAN_2].",
        )
        self.assertIn(
            IdentifierCategory.SPANISH_IDENTITY_CANDIDATE,
            minimized.detected_categories,
        )
        self.assertIn(
            IdentifierCategory.IBAN_CANDIDATE,
            minimized.detected_categories,
        )

    def test_non_spanish_iban_is_not_classified_as_an_iban(self) -> None:
        """Apply the generic numeric rule without claiming international IBAN support."""
        minimized = minimize_message_for_provider(
            "Cuenta DE89 3704 0044 0532 0130 00."
        )

        self.assertNotIn(
            IdentifierCategory.IBAN_CANDIDATE,
            minimized.detected_categories,
        )
        self.assertIn(
            IdentifierCategory.LONG_NUMERIC_CANDIDATE,
            minimized.detected_categories,
        )
        self.assertEqual(minimized.text, "Cuenta DE[NUMERO_LARGO_1].")

    def test_long_numeric_candidates_use_a_generic_privacy_label(self) -> None:
        """Redact ten or more digits without classifying them as payment cards."""
        short_value = minimize_message_for_provider("Código 123456789.")
        long_value = minimize_message_for_provider("Pedido 1234567890123.")

        self.assertEqual(short_value.text, "Código 123456789.")
        self.assertFalse(short_value.detected_categories)
        self.assertEqual(long_value.text, "Pedido [NUMERO_LARGO_1].")
        self.assertEqual(
            long_value.detected_categories,
            frozenset({IdentifierCategory.LONG_NUMERIC_CANDIDATE}),
        )


class OutputIdentifierDetectionTests(SimpleTestCase):
    """Verify output policy rejects candidates without rewriting provider text."""

    def test_long_numeric_candidates_are_explicitly_detected(self) -> None:
        """Reject long sequences while allowing ordinary short numbers."""
        detected = detect_output_identifier_candidates(
            "Referencia 1234567890"
        )
        ordinary_numbers = detect_output_identifier_candidates(
            "Llegó en 2026 y esperó 30 minutos."
        )

        self.assertIn(
            IdentifierCategory.LONG_NUMERIC_CANDIDATE,
            detected,
        )
        self.assertFalse(ordinary_numbers)

    def test_output_shape_detection_does_not_require_checksums(self) -> None:
        """Detect plausible Spanish identifiers with invalid check characters."""
        identity = detect_output_identifier_candidates(
            "DNI 12345678A y NIE X1234567A"
        )
        iban = detect_output_identifier_candidates(
            "IBAN ES00 0000 0000 0000 0000 0000"
        )

        self.assertIn(
            IdentifierCategory.SPANISH_IDENTITY_CANDIDATE,
            identity,
        )
        self.assertIn(IdentifierCategory.IBAN_CANDIDATE, iban)
