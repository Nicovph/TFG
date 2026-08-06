"""Validated cache access for content-free transient LLM controls."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import InvalidCacheBackendError, caches
from django.core.cache.backends.base import BaseCache
from django.core.cache.backends.dummy import DummyCache
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured


# These backends cannot coordinate markers across processes or containers.
UNSHARED_LLM_CACHE_BACKEND_TYPES = (DummyCache, LocMemCache)


def get_llm_transient_cache() -> BaseCache:
    """Resolve the cache used for content-free LLM control markers.

    The existing duplicate-cache setting is intentionally reused for attempt
    throttles and rate-limit audit deduplication. Distinct key namespaces keep
    those purposes separate without adding another cache dependency.

    Returns:
        The server-selected cache backend.

    Raises:
        ImproperlyConfigured: If the alias is unknown or a shared backend is
            required but the selected cache is process-local.
    """
    try:
        transient_cache = caches[settings.LLM_DUPLICATE_CACHE_ALIAS]
    except InvalidCacheBackendError as exc:
        raise ImproperlyConfigured(
            "LLM_DUPLICATE_CACHE_ALIAS debe apuntar a una caché configurada."
        ) from exc

    if (
        settings.LLM_REQUIRE_SHARED_DUPLICATE_CACHE
        and isinstance(
            transient_cache,
            UNSHARED_LLM_CACHE_BACKEND_TYPES,
        )
    ):
        raise ImproperlyConfigured(
            "LLM_DUPLICATE_CACHE_ALIAS debe apuntar a una caché compartida "
            "cuando LLM_REQUIRE_SHARED_DUPLICATE_CACHE está activo."
        )

    return transient_cache
