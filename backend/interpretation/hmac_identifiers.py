"""Domain-separated HMAC identifiers for privacy-minimised LLM state."""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def build_llm_hmac_digest(*, domain: str, value: str) -> str:
    """Create a backend-only HMAC digest for one transient LLM purpose.

    Args:
        domain: Fixed application-owned namespace separating independent uses.
        value: Transient internal material that must not appear in stored keys.

    Returns:
        A lowercase HMAC-SHA-256 hexadecimal digest.

    Raises:
        ValueError: If the trusted caller supplies an empty domain.
        ImproperlyConfigured: If the LLM-specific HMAC key is absent or short.
    """
    if not domain:
        raise ValueError("El dominio HMAC interno no puede estar vacío.")

    configured_key = settings.LLM_QUOTA_HMAC_KEY

    if not configured_key:
        raise ImproperlyConfigured(
            "Debe configurarse LLM_QUOTA_HMAC_KEY o "
            "LLM_QUOTA_HMAC_KEY_FILE."
        )

    key = configured_key.encode("utf-8")

    if len(key) < 32:
        raise ImproperlyConfigured(
            "LLM_QUOTA_HMAC_KEY debe contener al menos 32 bytes UTF-8."
        )

    return hmac.new(
        key,
        f"{domain}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
