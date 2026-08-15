"""Conservative semantic selection for validated ARASAAC search results."""

from __future__ import annotations

import unicodedata

from .contracts import (
    ArasaacPictogram,
    AvailablePictogram,
    build_image_url,
    normalize_external_label,
)


_DEFINITE_ARTICLES = frozenset({"el", "la", "los", "las"})


def _comparison_key(value: str) -> str:
    """Return an NFKC-stable key for caseless Unicode comparison.

    Args:
        value: Text to normalize exclusively for comparison.

    Returns:
        The NFKC-normalized and casefolded comparison key.
    """
    normalized = unicodedata.normalize("NFKC", value)
    return unicodedata.normalize("NFKC", normalized.casefold())


def _matches_with_inserted_article(*, concept_key: str, label_key: str) -> bool:
    """Allow only one internal definite article omitted by the concept.

    The direction and position are intentionally restricted. For example,
    ``abrir puerta`` may match ``abrir la puerta``, while a leading article in
    ``El Salvador`` cannot turn that country into a match for ``salvador``.

    Args:
        concept_key: Normalized concept comparison key.
        label_key: Normalized provider-label comparison key.

    Returns:
        True only when removing one internal definite article makes them equal.
    """
    concept_tokens = concept_key.split(" ")
    label_tokens = label_key.split(" ")
    if len(concept_tokens) < 2 or len(label_tokens) != len(concept_tokens) + 1:
        return False

    return any(
        label_tokens[index] in _DEFINITE_ARTICLES
        # Removes the token at position index and checks if the rest of the list is exactly equal to concept_tokens.
        and label_tokens[:index] + label_tokens[index + 1 :] == concept_tokens
        for index in range(1, len(label_tokens) - 1)
    )


def select_pictogram(
    *,
    concept: str,
    candidates: list[ArasaacPictogram],
    allow_inserted_article: bool,
) -> AvailablePictogram | None:
    """Select the strongest full-label match, preserving result order for ties.

    Literal equality is evaluated across the complete result set before the
    optional narrow article rule. This prevents an earlier approximate result
    from displacing a later exact match and rejects labels that add meaning.

    Args:
        concept: Canonical concept sent to ARASAAC.
        candidates: Strictly validated provider candidates.
        allow_inserted_article: Whether to accept one omitted internal article.

    Returns:
        The first match under the enabled policy, or None when none is safe.
    """
    concept_key = _comparison_key(concept)
    # Prefer exact matches; only fall back to the inserted-article rule if enabled.
    match_modes = (False, True) if allow_inserted_article else (False,)
    for use_inserted_article in match_modes:
        for candidate in candidates:
            for keyword in candidate.keywords:
                # ARASAAC provides separate image resources for singular and
                # plural forms, so the matched form travels with the label.
                for external_value, plural in (
                    (keyword.keyword, False),
                    (keyword.plural, True),
                ):
                    if external_value is None:
                        continue
                    label = normalize_external_label(external_value)
                    # Drop labels that do not survive the external normalization policy.
                    if label is None:
                        continue

                    label_key = _comparison_key(label)
                    # Exact equality, or the narrow internal-article exception.
                    matches = (
                        _matches_with_inserted_article(
                            concept_key=concept_key,
                            label_key=label_key,
                        )
                        if use_inserted_article
                        else label_key == concept_key
                    )
                    if not matches:
                        continue

                    pictogram_id = candidate.pictogram_id
                    return AvailablePictogram(
                        concept=concept,
                        pictogram_id=pictogram_id,
                        label=label,
                        image_url=build_image_url(
                            pictogram_id=pictogram_id,
                            plural=plural,
                        ),
                    )

    return None
