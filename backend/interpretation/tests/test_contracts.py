"""Adversarial tests for Pydantic contracts and privacy business rules."""

import json

from django.test import SimpleTestCase
from pydantic import ValidationError

from backend.preferences.models import InterpretationDetail, UserPreferences

from ..contracts import (
    LLMInterpretationOutput,
    OutputBusinessRuleError,
    validate_output_business_rules,
)
from .helpers import valid_output_payload


class StructuredOutputContractTests(SimpleTestCase):
    """Reject malformed provider output even when JSON parsing succeeds."""

    def test_closed_schema_requires_every_field_and_correct_types(self) -> None:
        """Reject missing, additional, and incorrectly typed fields."""
        payloads = []

        missing = valid_output_payload()
        missing.pop("signals")
        payloads.append(missing)

        additional = valid_output_payload()
        additional["model"] = "attacker-selected"
        payloads.append(additional)

        wrong_type = valid_output_payload()
        wrong_type["needs_more_context"] = "false"
        payloads.append(wrong_type)

        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                LLMInterpretationOutput.model_validate_json(json.dumps(payload))

    def test_json_schema_closes_root_and_nested_objects(self) -> None:
        """Produce the strict-mode requirements expected by Groq."""
        schema = LLMInterpretationOutput.model_json_schema()

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        signal_schema = schema["$defs"]["PragmaticSignal"]
        self.assertFalse(signal_schema["additionalProperties"])
        self.assertEqual(
            set(signal_schema["required"]),
            set(signal_schema["properties"]),
        )
        self.assertIn(
            "significado pragmático",
            schema["properties"]["interpretation"]["description"],
        )
        self.assertIn(
            "contexto que falta",
            schema["properties"]["context_note"]["description"],
        )

    def test_signal_kinds_are_closed_and_express_uncertainty(self) -> None:
        """Accept only the six cautious server-defined signal identifiers."""
        allowed_kinds = (
            "possible_irony",
            "possible_ambiguity",
            "possible_indirect_language",
            "possible_offensive_language",
            "possible_aggression",
            "possible_cyberbullying",
        )

        for signal_kind in allowed_kinds:
            payload = valid_output_payload()
            payload["signals"] = [
                {
                    "kind": signal_kind,
                    "explanation": "La señal necesita interpretación contextual.",
                }
            ]

            with self.subTest(signal_kind=signal_kind):
                output = LLMInterpretationOutput.model_validate(payload)
                self.assertEqual(output.signals[0].kind, signal_kind)

        for legacy_kind in ("irony", "ambiguity", "indirect_language"):
            payload = valid_output_payload()
            payload["signals"] = [
                {
                    "kind": legacy_kind,
                    "explanation": "La señal necesita interpretación contextual.",
                }
            ]

            with self.subTest(legacy_kind=legacy_kind), self.assertRaises(
                ValidationError
            ):
                LLMInterpretationOutput.model_validate(payload)

    def test_business_rules_reject_message_reproduction_and_phrases(self) -> None:
        """Prevent ARASAAC concepts from becoming a copy of user text."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.STANDARD,
            visual_support_enabled=True,
        )
        reproducing_payload = valid_output_payload()
        reproducing_payload["visual_concepts"] = ["cierra", "la ventana"]
        reproducing = LLMInterpretationOutput.model_validate(reproducing_payload)

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=reproducing,
                analyzed_message="Cierra la ventana",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "Los conceptos visuales reproducen el mensaje.",
        )

        punctuated_payload = valid_output_payload()
        punctuated_payload["visual_concepts"] = ["hola", "amigo"]
        punctuated = LLMInterpretationOutput.model_validate(punctuated_payload)

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=punctuated,
                analyzed_message="¡Hola, amigo!",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "Los conceptos visuales reproducen el mensaje.",
        )

        phrase_payload = valid_output_payload()
        phrase_payload["visual_concepts"] = ["esta frase tiene demasiadas palabras"]
        phrase = LLMInterpretationOutput.model_validate(phrase_payload)

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=phrase,
                analyzed_message="Otro mensaje",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "Un concepto visual no es atómico.",
        )

    def test_business_rules_normalize_unicode_and_reject_lexical_duplicates(
        self,
    ) -> None:
        """Canonicalize concepts before ARASAAC and reject equivalent tokens."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.STANDARD,
            visual_support_enabled=True,
        )
        decomposed_payload = valid_output_payload()
        decomposed_payload["visual_concepts"] = ["cafe\u0301"]
        decomposed = LLMInterpretationOutput.model_validate(decomposed_payload)

        canonical = validate_output_business_rules(
            output=decomposed,
            analyzed_message="Preparar una bebida",
            preferences=preferences,
            max_visual_concepts=5,
            max_visual_concept_characters=40,
        )

        self.assertEqual(canonical.visual_concepts, ["café"])

        duplicate_payload = valid_output_payload()
        duplicate_payload["visual_concepts"] = ["auto-estima", "auto estima"]
        duplicate = LLMInterpretationOutput.model_validate(duplicate_payload)

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=duplicate,
                analyzed_message="Mensaje diferente",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "Los conceptos visuales deben ser únicos.",
        )

    def test_business_rules_reject_external_references_and_markup(self) -> None:
        """Reject closed disallowed output forms without broad colon matching."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.STANDARD,
            visual_support_enabled=True,
        )
        disallowed_values = (
            "https://example.org",
            "www.example.org",
            "//example.org/path",
            "javascript:alert(1)",
            "data:text/html,contenido",
            "file:///tmp/example",
            "ftp://example.org",
            "mailto:persona@example.org",
            "blob:https://example.org/id",
            "tel:+34123456789",
            "<strong>contenido</strong>",
            "persona@example.org",
        )

        for disallowed_value in disallowed_values:
            payload = valid_output_payload()
            payload["interpretation"] = (
                f"Referencia no permitida: {disallowed_value}"
            )
            output = LLMInterpretationOutput.model_validate(payload)

            with self.subTest(disallowed_value=disallowed_value), self.assertRaises(
                OutputBusinessRuleError
            ) as raised:
                validate_output_business_rules(
                    output=output,
                    analyzed_message="Mensaje diferente",
                    preferences=preferences,
                    max_visual_concepts=5,
                    max_visual_concept_characters=40,
                )

            self.assertEqual(
                str(raised.exception),
                "La salida contiene una URL, una dirección de correo electrónico, "
                "un esquema URI o marcado no permitidos.",
            )

        allowed_payload = valid_output_payload()
        allowed_payload["interpretation"] = "Nota: falta contexto suficiente."
        allowed_output = LLMInterpretationOutput.model_validate(allowed_payload)

        validate_output_business_rules(
            output=allowed_output,
            analyzed_message="Mensaje diferente",
            preferences=preferences,
            max_visual_concepts=5,
            max_visual_concept_characters=40,
        )

    def test_business_rules_honor_visual_and_detail_preferences(self) -> None:
        """Enforce closed server preferences after provider validation."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.BRIEF,
            visual_support_enabled=False,
        )
        excessive_detail_payload = valid_output_payload()
        excessive_detail_payload["interpretation"] = "x" * 421
        excessive_detail_output = LLMInterpretationOutput.model_validate(
            excessive_detail_payload
        )

        with self.assertRaises(OutputBusinessRuleError):
            validate_output_business_rules(
                output=excessive_detail_output,
                analyzed_message="Mensaje",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        visual_output = LLMInterpretationOutput.model_validate(
            valid_output_payload()
        )

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=visual_output,
                analyzed_message="Mensaje",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "Los conceptos visuales están desactivados.",
        )

    def test_business_rules_reject_direct_identifiers_in_output(self) -> None:
        """Prevent generated text or concepts from carrying direct identifiers."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.STANDARD,
            visual_support_enabled=True,
        )
        payload = valid_output_payload()
        payload["visual_concepts"] = ["612345678"]
        output = LLMInterpretationOutput.model_validate(payload)

        with self.assertRaises(OutputBusinessRuleError):
            validate_output_business_rules(
                output=output,
                analyzed_message="Mensaje genérico",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

    def test_business_rules_reject_long_numeric_identifiers_in_all_output(
        self,
    ) -> None:
        """Reject long numeric candidates in explanatory text and concepts."""
        preferences = UserPreferences(
            interpretation_detail=InterpretationDetail.STANDARD,
            visual_support_enabled=True,
        )

        for field_name in ("interpretation", "clear_reformulation"):
            payload = valid_output_payload()
            payload[field_name] = "Referencia 1234567890"
            output = LLMInterpretationOutput.model_validate(payload)

            with self.subTest(field_name=field_name), self.assertRaises(
                OutputBusinessRuleError
            ) as raised:
                validate_output_business_rules(
                    output=output,
                    analyzed_message="Mensaje genérico",
                    preferences=preferences,
                    max_visual_concepts=5,
                    max_visual_concept_characters=40,
                )

            self.assertEqual(
                str(raised.exception),
                "La salida contiene un candidato a identificador numérico largo.",
            )

        concept_payload = valid_output_payload()
        concept_payload["visual_concepts"] = ["1234567890"]
        concept_output = LLMInterpretationOutput.model_validate(concept_payload)

        with self.assertRaises(OutputBusinessRuleError) as raised:
            validate_output_business_rules(
                output=concept_output,
                analyzed_message="Mensaje genérico",
                preferences=preferences,
                max_visual_concepts=5,
                max_visual_concept_characters=40,
            )

        self.assertEqual(
            str(raised.exception),
            "La salida contiene un candidato a identificador numérico largo.",
        )
