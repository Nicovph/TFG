"""Orchestrate privacy-minimised ARASAAC lookup and textual fallbacks."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from collections.abc import Sequence

import httpx
from asgiref.sync import async_to_sync
from django.conf import settings

from backend.audit.request_context import get_current_request_id

from ..contracts import CONCEPT_PATTERN
from .client import (
    ARASAAC_API_ORIGIN,
    _ArasaacHttpStatusError,
    _ArasaacResponseError,
    search_concept,
)
from .contracts import (
    ArasaacAttribution,
    AvailablePictogram,
    MissingPictogram,
    VisualSupportResult,
)


logger = logging.getLogger(__name__)


def _canonicalize_concepts(concepts: Sequence[str]) -> tuple[str, ...]:
    """Revalidate minimized concepts at the network boundary.

    Business validation already occurs after LLM interpretation. Repeating the
    closed checks here is deliberate defense in depth: future internal callers
    cannot accidentally send a message or arbitrary text to ARASAAC.

    Args:
        concepts: Candidate visual concepts produced by validated interpretation.

    Raises:
        ValueError: If the sequence or any concept violates the closed policy.

    Returns:
        Canonical unique concepts in their original order.
    """
    if isinstance(concepts, (str, bytes)) or not isinstance(concepts, Sequence):
        raise ValueError("Los conceptos visuales deben formar una secuencia.")

    if len(concepts) > settings.LLM_MAX_VISUAL_CONCEPTS:
        raise ValueError("Hay demasiados conceptos visuales.")

    canonical_concepts: list[str] = []
    comparison_keys: set[str] = set()

    for concept in concepts:
        # ``bool`` and arbitrary objects must not be coerced to strings at this
        # trust boundary; only a real string from the validated contract is valid.
        if type(concept) is not str:
            raise ValueError("Cada concepto visual debe ser texto.")

        canonical = re.sub(
            r" {2,}",
            " ",
            unicodedata.normalize("NFKC", concept).strip(),
        )
        comparison_key = canonical.casefold()

        if (
            not canonical
            or len(canonical) > settings.LLM_MAX_VISUAL_CONCEPT_CHARACTERS
            or not CONCEPT_PATTERN.fullmatch(canonical)
            or comparison_key in comparison_keys
        ):
            raise ValueError("Un concepto visual no supera la política cerrada.")

        canonical_concepts.append(canonical)
        comparison_keys.add(comparison_key)

    return tuple(canonical_concepts)


def _build_visual_support_result(
    *,
    items: list[AvailablePictogram | MissingPictogram],
) -> VisualSupportResult:
    """Derive one low-cognitive-load summary from per-concept results.

    Args:
        items: Validated pictogram or fallback result for each concept.

    Returns:
        A coherent aggregate status, message, items, and attribution.
    """
    available_count = sum(item.status == "available" for item in items)

    if not items:
        status = "not_requested"
        message = ""
    elif available_count == len(items):
        status = "complete"
        message = ""
    elif available_count:
        status = "partial"
        if any(item.status == "temporarily_unavailable" for item in items):
            message = (
                "Algunos pictogramas no se pudieron cargar. "
                "La interpretación de texto sigue disponible."
            )
        else:
            message = (
                "Algunos conceptos no tienen un pictograma claro. "
                "La interpretación de texto sigue disponible."
            )
    else:
        status = "unavailable"
        if any(item.status == "temporarily_unavailable" for item in items):
            message = (
                "Los pictogramas no se pudieron cargar. "
                "La interpretación de texto sigue disponible."
            )
        else:
            message = (
                "No se encontraron pictogramas claros. "
                "La interpretación de texto sigue disponible."
            )

    # Attribution is included only when at least one licensed resource is used;
    # the model validator checks that this stays coherent with the summary.
    return VisualSupportResult(
        status=status,
        items=items,
        message=message,
        attribution=ArasaacAttribution() if available_count else None,
    )


def build_unavailable_visual_support(
    *,
    concepts: Sequence[str],
) -> VisualSupportResult:
    """Build a safe all-unavailable fallback at the service boundary.

    This function performs no network access. It lets the interpretation service
    preserve its successful textual response even if an unexpected integration
    error escapes the narrower provider failure handling.

    Args:
        concepts: Visual concepts to preserve in the fallback response.

    Raises:
        ValueError: If the sequence or any concept violates the closed policy.

    Returns:
        A fallback marking every canonical concept as temporarily unavailable.
    """
    canonical_concepts = _canonicalize_concepts(concepts)
    return _build_visual_support_result(
        items=[
            MissingPictogram(
                concept=concept,
                status="temporarily_unavailable",
            )
            for concept in canonical_concepts
        ]
    )


async def _lookup_visual_support(
    *,
    canonical_concepts: tuple[str, ...],
    transport: httpx.AsyncBaseTransport | None,
) -> VisualSupportResult:
    """Resolve all concepts under one cancelable wall-clock budget.

    Args:
        canonical_concepts: Validated concepts in response order.
        transport: Optional HTTPX transport for deterministic tests.

    Returns:
        Available pictograms and explicit fallbacks for all concepts.
    """
    started = time.monotonic()
    items: list[AvailablePictogram | MissingPictogram] = []
    provider_error_type: str | None = None

    try:
        # HTTPX phase timeouts limit individual waits; asyncio.timeout bounds the
        # complete sequence, including DNS, all concepts, streaming, and cleanup.
        async with asyncio.timeout(float(settings.ARASAAC_TOTAL_TIMEOUT_SECONDS)):
            async with httpx.AsyncClient(
                base_url=ARASAAC_API_ORIGIN,
                follow_redirects=False,
                trust_env=False,
                # Enables SSL/TLS verification.
                verify=True,
                timeout=httpx.Timeout(
                    float(settings.ARASAAC_READ_TIMEOUT_SECONDS),
                    connect=float(settings.ARASAAC_CONNECT_TIMEOUT_SECONDS),
                ),
                transport=transport,
            ) as client:
                # Requests are deliberately sequential. This avoids a burst of
                # third-party traffic and preserves the validated concept order.
                for concept in canonical_concepts:
                    pictogram = await search_concept(
                        client=client,
                        concept=concept,
                    )
                    items.append(
                        pictogram
                        if pictogram is not None
                        else MissingPictogram(
                            concept=concept,
                            status="not_found",
                        )
                    )
    except TimeoutError:
        provider_error_type = "total_timeout"
    except httpx.TimeoutException:
        provider_error_type = "timeout"
    except httpx.RequestError:
        provider_error_type = "transport"
    except _ArasaacHttpStatusError:
        provider_error_type = "http_status"
    except _ArasaacResponseError:
        provider_error_type = "invalid_response"

    if provider_error_type is not None:
        # Preserve any successful earlier items and degrade only the unresolved
        # suffix. Logs contain a closed category, never concepts or provider data.
        failure_index = len(items)
        items.extend(
            MissingPictogram(
                concept=concept,
                status="temporarily_unavailable",
            )
            for concept in canonical_concepts[failure_index:]
        )
        logger.warning(
            "arasaac_lookup outcome=degraded error_type=%s "
            "concept_count=%d duration_ms=%d request_id=%s",
            provider_error_type,
            len(canonical_concepts),
            max(0, int((time.monotonic() - started) * 1000)),
            get_current_request_id() or "none",
        )

    return _build_visual_support_result(items=items)


def _get_visual_support(
    *,
    concepts: Sequence[str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> VisualSupportResult:
    """Resolve concepts through an optionally injected internal transport.

    ``async_to_sync`` is the supported asgiref bridge for this synchronous
    Django service boundary and composes with Django's ASGI adaptation. The
    injectable transport exists only for deterministic, network-free tests.

    Args:
        concepts: Minimized visual concepts produced by the interpretation.
        transport: Optional HTTPX transport for deterministic tests.

    Raises:
        ValueError: If the sequence or any concept violates the closed policy.

    Returns:
        Validated pictogram results or text-preserving fallback states.
    """
    canonical_concepts = _canonicalize_concepts(concepts)
    if not canonical_concepts:
        # Avoid creating an event loop and HTTP client for an empty validated list.
        return _build_visual_support_result(items=[])
    return async_to_sync(_lookup_visual_support)(
        canonical_concepts=canonical_concepts,
        transport=transport,
    )


def get_visual_support(
    *,
    concepts: Sequence[str],
) -> VisualSupportResult:
    """Resolve a bounded concept list through the fixed production transport.

    Args:
        concepts: Minimized visual concepts produced by the interpretation.

    Raises:
        ValueError: If the sequence or any concept violates the closed policy.

    Returns:
        Validated pictogram results or text-preserving fallback states.
    """
    return _get_visual_support(concepts=concepts)
