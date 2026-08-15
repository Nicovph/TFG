import asyncio
from collections.abc import AsyncIterator

import httpx


ARASAAC_TEST_SETTINGS = {
    "ARASAAC_CONNECT_TIMEOUT_SECONDS": 2,
    "ARASAAC_READ_TIMEOUT_SECONDS": 3,
    "ARASAAC_TOTAL_TIMEOUT_SECONDS": 5,
    "LLM_MAX_VISUAL_CONCEPTS": 5,
    "LLM_MAX_VISUAL_CONCEPT_CHARACTERS": 40,
}


class SlowJsonStream(httpx.AsyncByteStream):
    """Emit valid-looking JSON fragments until the total budget is exhausted."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield fragments often enough that an inactivity timeout never fires."""
        yield b"["
        while True:
            await asyncio.sleep(0.01)
            yield b" "


class UnreadableJsonStream(httpx.AsyncByteStream):
    """Fail if a rejected content encoding reaches the body reader."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Raise if security checks attempt to read this encoded body."""
        raise AssertionError("No debía leerse un cuerpo comprimido.")
        yield b""  # pragma: no cover - keeps this method an async generator.


class ExcessiveJsonStream(httpx.AsyncByteStream):
    """Cross the byte ceiling and fail if the reader requests another chunk."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield two oversized fragments without exposing the guarded tail."""
        yield b"[" + (b" " * 200_000)
        yield b" " * 70_000
        raise AssertionError("No debía consumirse el resto del cuerpo excesivo.")
