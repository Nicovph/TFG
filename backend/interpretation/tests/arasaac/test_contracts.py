"""Test closed public contracts for ARASAAC visual support."""

from django.test import SimpleTestCase
from pydantic import ValidationError

from ...arasaac import (
    ArasaacAttribution,
    AvailablePictogram,
    MissingPictogram,
    VisualSupportResult,
)


class ArasaacContractTests(SimpleTestCase):
    """Verify the closed public visual support contracts."""

    def test_message_whitespace_is_normalized_before_summary_validation(self) -> None:
        """Normalize whitespace before enforcing the fallback message invariant."""
        available_item = AvailablePictogram(
            concept="futuro",
            pictogram_id=9829,
            label="futuro",
            image_url="https://static.arasaac.org/pictograms/9829/9829_300.png",
        )
        missing_item = MissingPictogram(concept="viaje", status="not_found")
        attribution = ArasaacAttribution()

        for status, items, expected_attribution in (
            ("unavailable", [missing_item], None),
            ("partial", [available_item, missing_item], attribution),
        ):
            with self.subTest(status=status), self.assertRaises(ValidationError):
                VisualSupportResult(
                    status=status,
                    items=items,
                    message="   ",
                    attribution=expected_attribution,
                )

        for status, items, expected_attribution in (
            ("not_requested", [], None),
            ("complete", [available_item], attribution),
        ):
            with self.subTest(status=status):
                result = VisualSupportResult(
                    status=status,
                    items=items,
                    message="   ",
                    attribution=expected_attribution,
                )

                self.assertEqual(result.message, "")

    def test_item_status_is_a_closed_discriminator(self) -> None:
        """Select item variants by status and reject an unknown discriminator tag."""
        payload = {
            "status": "partial",
            "items": [
                {
                    "concept": "futuro",
                    "status": "available",
                    "pictogram_id": 9829,
                    "label": "futuro",
                    "image_url": (
                        "https://static.arasaac.org/pictograms/9829/9829_300.png"
                    ),
                },
                {"concept": "viaje", "status": "not_found"},
            ],
            "message": "No se encontró todo el apoyo visual.",
            "attribution": {},
        }

        result = VisualSupportResult.model_validate(payload)

        self.assertIsInstance(result.items[0], AvailablePictogram)
        self.assertIsInstance(result.items[1], MissingPictogram)

        payload["items"][1]["status"] = "unknown"
        with self.assertRaises(ValidationError) as captured:
            VisualSupportResult.model_validate(payload)

        self.assertEqual(captured.exception.errors()[0]["type"], "union_tag_invalid")

    def test_label_and_identifier_boundaries_are_interoperable(self) -> None:
        """Keep labels bounded and IDs safely distinguishable in JavaScript."""
        safe_identifier = 2**53 - 1
        image_url = (
            "https://static.arasaac.org/pictograms/"
            f"{safe_identifier}/{safe_identifier}_300.png"
        )
        pictogram = AvailablePictogram(
            concept="límite",
            pictogram_id=safe_identifier,
            label="a" * 96,
            image_url=image_url,
        )

        self.assertEqual(pictogram.pictogram_id, safe_identifier)
        with self.assertRaises(ValidationError):
            AvailablePictogram(
                concept="límite",
                pictogram_id=safe_identifier,
                label="a" * 97,
                image_url=image_url,
            )
        with self.assertRaises(ValidationError):
            AvailablePictogram(
                concept="límite",
                pictogram_id=2**53,
                label="límite",
                image_url=(
                    "https://static.arasaac.org/pictograms/"
                    f"{2**53}/{2**53}_300.png"
                ),
            )

    def test_public_contract_rejects_arbitrary_urls_and_inconsistent_summary(
        self,
    ) -> None:
        """Prevent future callers from bypassing derived resource invariants."""
        with self.assertRaises(ValidationError):
            AvailablePictogram(
                concept="futuro",
                pictogram_id=9829,
                label="futuro",
                image_url="https://example.invalid/9829.png",
            )

        valid_item = AvailablePictogram(
            concept="futuro",
            pictogram_id=9829,
            label="futuro",
            image_url=(
                "https://static.arasaac.org/pictograms/9829/9829_300.png"
            ),
        )
        with self.assertRaises(ValidationError):
            VisualSupportResult(
                status="complete",
                items=[valid_item],
                message="",
                attribution=None,
            )
