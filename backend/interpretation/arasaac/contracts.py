"""Closed public and provider-facing contracts for ARASAAC visual support."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)


# Image resources.
ARASAAC_IMAGE_ORIGIN = "https://static.arasaac.org"
ARASAAC_IMAGE_RESOLUTION = 300

# The HTTP client bounds collection sizes through its response byte ceiling.
# Labels retain a separate processing budget above the current catalogue maximum,
# while IDs must remain safe integers across ARASAAC and React JS Numbers (Number.MAX_SAFE_INTEGER).
MAX_EXTERNAL_LABEL_CHARACTERS = 96
MAX_PICTOGRAM_ID = 2**53 - 1

_SAFE_LABEL_PATTERN = re.compile(
    r"[^\W_]+(?:-[^\W_]+)*(?: [^\W_]+(?:-[^\W_]+)*){0,5}"
)

Concept = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=64,
    ),
]
# ARASAAC labels may be words or phrases; local policy bounds and normalizes a simple label.
ExternalLabel = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_EXTERNAL_LABEL_CHARACTERS,
    ),
]
ExternalPlural = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        max_length=MAX_EXTERNAL_LABEL_CHARACTERS,
    ),
]


def normalize_external_label(value: str) -> str | None:
    """Return a simple display label, rejecting active or complex text.

    This normalization is shared by semantic matching and the public model
    validator. Keeping one policy prevents a value accepted during selection
    from being interpreted differently when serialized for the frontend.

    Args:
        value: Provider label to normalize and validate.

    Returns:
        The normalized safe label, or None when the label is not allowed.
    """
    # Normalize to NFKC, strip leading/trailing whitespace, and collapse consecutive spaces
    normalized = re.sub(
        r" {2,}",
        " ",
        unicodedata.normalize("NFKC", value).strip(),
    )
    if not normalized or not _SAFE_LABEL_PATTERN.fullmatch(normalized):
        return None
    return normalized


def build_image_url(*, pictogram_id: int, plural: bool) -> str:
    """Derive a static PNG URL exclusively from validated local values.

    Args:
        pictogram_id: Validated positive ARASAAC pictogram identifier.
        plural: Whether to select ARASAAC's plural image variant.

    Returns:
        The HTTPS URL derived from the fixed image origin and validated values.
    """
    plural_modifier = "_plural" if plural else ""
    return (
        f"{ARASAAC_IMAGE_ORIGIN}/pictograms/{pictogram_id}/"
        f"{pictogram_id}{plural_modifier}_{ARASAAC_IMAGE_RESOLUTION}.png"
    )


class ArasaacAttribution(BaseModel):
    """Expose the attribution required when an ARASAAC pictogram is used."""

    model_config = ConfigDict(extra="forbid", strict=True)

    # Fixed credit text enforced as a Literal constant (type + runtime).
    text: Literal[
        "Autor pictogramas: Sergio Palao. "
        "Procedencia: ARASAAC (https://arasaac.org). "
        "Licencia: CC (BY-NC-SA). Propiedad: Gobierno de Aragón (España)."
    ] = (
        "Autor pictogramas: Sergio Palao. "
        "Procedencia: ARASAAC (https://arasaac.org). "
        "Licencia: CC (BY-NC-SA). Propiedad: Gobierno de Aragón (España)."
    )
    terms_url: Literal["https://arasaac.org/terms-of-use"] = (
        "https://arasaac.org/terms-of-use"
    )


class AvailablePictogram(BaseModel):
    """Represent one conservatively matched ARASAAC pictogram."""

    model_config = ConfigDict(extra="forbid", strict=True)

    concept: Concept
    status: Literal["available"] = "available"
    pictogram_id: int = Field(strict=True, gt=0, le=MAX_PICTOGRAM_ID)
    label: ExternalLabel
    image_url: str = Field(strict=True, min_length=1, max_length=200)

    # After field validation: ensure image_url and label follow the closed policy.
    # Must return self to confirm the model instance is valid.
    @model_validator(mode="after")
    def validate_safe_resource(self) -> AvailablePictogram:
        """Reject URLs and labels that were not derived by the closed policy.

        Raises:
            ValueError: If the image URL or display label violates the policy.

        Returns:
            The validated pictogram model.
        """
        allowed_urls = {
            build_image_url(pictogram_id=self.pictogram_id, plural=False),
            build_image_url(pictogram_id=self.pictogram_id, plural=True),
        }
        if (
            self.image_url not in allowed_urls
            or normalize_external_label(self.label) != self.label
        ):
            raise ValueError("El recurso visual no supera la política cerrada.")
        return self


class MissingPictogram(BaseModel):
    """Represent a concept without a safe pictogram result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    concept: Concept
    status: Literal["not_found", "temporarily_unavailable"]


class VisualSupportResult(BaseModel):
    """Represent bounded pictogram results and a text-preserving fallback."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["not_requested", "complete", "partial", "unavailable"]
    items: list[
        Annotated[AvailablePictogram | MissingPictogram, Field(discriminator="status")]
    ] = Field(max_length=10)
    message: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, max_length=140),
    ]
    attribution: ArasaacAttribution | None

    @model_validator(mode="after")
    def validate_summary(self) -> VisualSupportResult:
        """Reject contradictory status, fallback, and attribution combinations.

        Raises:
            ValueError: If status, message, items, and attribution disagree.

        Returns:
            The validated visual support result.
        """
        available_count = sum(item.status == "available" for item in self.items)
        if not self.items:
            expected_status = "not_requested"
        elif available_count == len(self.items):
            expected_status = "complete"
        elif available_count:
            expected_status = "partial"
        else:
            expected_status = "unavailable"

        requires_message = expected_status not in {"complete", "not_requested"}
        if (
            self.status != expected_status
            or bool(self.attribution) != bool(available_count)
            or bool(self.message) != requires_message
        ):
            raise ValueError("El resumen de apoyo visual es incoherente.")
        return self


class ArasaacKeyword(BaseModel):
    """Validate only external keyword fields used for matching."""

    model_config = ConfigDict(extra="ignore", strict=True)

    keyword: ExternalLabel
    plural: ExternalPlural | None = None


class ArasaacPictogram(BaseModel):
    """Validate the minimal external pictogram projection used by Django."""

    model_config = ConfigDict(extra="ignore", strict=True)

    pictogram_id: int = Field(
        alias="_id",
        strict=True,
        gt=0,
        le=MAX_PICTOGRAM_ID,
    )
    keywords: list[ArasaacKeyword] = Field(min_length=1)


# A module-level adapter avoids rebuilding Pydantic's schema for every concept.
SEARCH_RESPONSE_ADAPTER = TypeAdapter(list[ArasaacPictogram])
