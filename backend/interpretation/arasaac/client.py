"""Bounded HTTP trust boundary for the public ARASAAC API."""

from __future__ import annotations

import json
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .contracts import SEARCH_RESPONSE_ADAPTER, AvailablePictogram
from .matching import select_pictogram


ARASAAC_API_ORIGIN = "https://api.arasaac.org"
ARASAAC_LANGUAGE = "es"

# The ceiling applies to identity-encoded raw bytes before JSON decoding. It is
# independent of deployment settings so a configuration error cannot make an
# untrusted provider response consume unbounded memory.
_MAX_RESPONSE_BYTES = 256 * 1024


class _ArasaacResponseError(RuntimeError):
    """Indicate an invalid or excessive untrusted ARASAAC response."""


class _ArasaacHttpStatusError(RuntimeError):
    """Indicate an unexpected status without retaining its response body."""


async def _read_bounded_json(response: httpx.Response) -> object:
    """Read identity-encoded JSON under a raw byte ceiling.

    Media type and content encoding are checked before body iteration. Requesting
    identity encoding and using ``aiter_raw`` avoids transparently expanding a
    compressed response before the byte limit can be enforced.

    Args:
        response: Streaming ARASAAC response to validate and decode.

    Raises:
        _ArasaacResponseError: If metadata, size, encoding, or JSON is invalid.

    Returns:
        The decoded JSON value without assuming its schema.
    """
    media_type = (
        response.headers.get("Content-Type", "")
        .split(";", maxsplit=1)[0]
        .strip()
        .casefold()
    )
    if media_type != "application/json":
        raise _ArasaacResponseError("invalid_media_type")

    content_encoding = response.headers.get("Content-Encoding", "").casefold()
    # Cases in which it is not necessary to perform explicit decompression of the received data.
    if content_encoding not in {"", "identity"}:
        raise _ArasaacResponseError("invalid_content_encoding")

    # Mutable buffer so chunks can be appended efficiently under a size ceiling.
    content = bytearray()

    def append_chunk(chunk: bytes) -> None:
        """Append a raw chunk only while it remains inside the ceiling.

        Args:
            chunk: Raw response bytes to append.

        Raises:
            _ArasaacResponseError: If the response would exceed the byte ceiling.
        """
        # Reject before extending so the limit is never crossed in memory.
        if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise _ArasaacResponseError("response_too_large")
        content.extend(chunk)

    # MockTransport may expose an already consumed response while production
    # streaming responses are read incrementally. Both paths enforce one limit.
    if response.is_stream_consumed:
        # Body already materialised (typical in tests).
        append_chunk(response.content)
    else:
        # Stream raw bytes to avoid decompression before the size check.
        async for chunk in response.aiter_raw():
            append_chunk(chunk)

    try:
        # Decode only after the byte ceiling has been fully enforced.
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        # Suppress untrusted parser details from standard tracebacks.
        raise _ArasaacResponseError("invalid_json") from None


async def search_concept(
    *,
    client: httpx.AsyncClient,
    concept: str,
) -> AvailablePictogram | None:
    """Search one minimized concept through fixed, bounded API routes.

    Args:
        client: Request-local client bound to the trusted ARASAAC origin.
        concept: Canonical simple concept; never a message or explanation.

    Raises:
        httpx.RequestError: If the HTTPS request fails.
        _ArasaacHttpStatusError: If ARASAAC returns an unexpected status.
        _ArasaacResponseError: If an external response violates the policy.

    Returns:
        An exact or narrowly article-equivalent pictogram, if one is safe.
    """
    # Percent-encode the full concept so it is safe inside the path segment.
    encoded_concept = quote(concept, safe="")
    # bestsearch returns only exact keyword/plural matches. The broader search
    # is used solely for multi-word concepts that may omit one internal article.
    operations = ("bestsearch", "search") if " " in concept else ("bestsearch",)

    for operation in operations:
        search_path = (
            f"/v1/pictograms/{ARASAAC_LANGUAGE}/{operation}/{encoded_concept}"
        )
        # Never carry provider-controlled state between minimized requests.
        # Drop any cookies left by previous responses to keep requests isolated.
        client.cookies.clear()
        async with client.stream(
            "GET",
            search_path,
            headers={
                # Demand JSON and forbid transparent compression so the byte
                # ceiling can be enforced on the raw body.
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            follow_redirects=False,
        ) as response:
            if response.status_code not in (200, 404):
                raise _ArasaacHttpStatusError("unexpected_status")
            payload = await _read_bounded_json(response)

        # ARASAAC represents an empty search as 404 plus an empty array.
        if response.status_code == 404:
            if payload != []:
                raise _ArasaacResponseError("invalid_not_found_response")
            continue

        # Strict schema validation: no type coercion, no extra fields.
        try:
            candidates = SEARCH_RESPONSE_ADAPTER.validate_python(
                payload,
                strict=True,
            )
        except (ValidationError, RecursionError):
            # Suppress untrusted validator details from standard tracebacks.
            raise _ArasaacResponseError("invalid_schema") from None

        pictogram = select_pictogram(
            concept=concept,
            candidates=candidates,
            allow_inserted_article=operation == "search",
        )
        if pictogram is not None:
            return pictogram

    return None
