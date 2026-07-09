"""PKCE helper functions for the Google authorization code flow."""

import base64
import hashlib
import secrets

from .exceptions import GoogleOIDCConfigurationError


PKCE_CODE_CHALLENGE_METHOD = "S256"


def create_pkce_code_verifier() -> str:
    """Create a high-entropy PKCE code verifier.

    Returns:
        A URL-safe verifier between 43 and 128 characters.

    Raises:
        GoogleOIDCConfigurationError: If the generated verifier does not meet
            the PKCE length constraints.
    """
    # secrets.token_urlsafe(nbytes=None) where nbytes specify how many bytes of random entropy you want to generate.
    verifier = secrets.token_urlsafe(64)

    # In base64, 3 bites = 4 characters, so 64 * 4 / 3 =~ 85, so this comprobation is for hardiness.
    if not 43 <= len(verifier) <= 128:
        raise GoogleOIDCConfigurationError(
            "El code_verifier PKCE generado no cumple la longitud requerida."
        )

    return verifier


def create_pkce_code_challenge(code_verifier: str) -> str:
    """Derive the S256 PKCE code challenge for a verifier.

    Args:
        code_verifier: The high-entropy verifier generated for this flow.

    Returns:
        The base64url-encoded SHA-256 challenge without padding.
    """
    # Encode the verifier as ASCII raw bytes.
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    # rstrip removes trailing padding = characters and decode converts the base64 bytes to an Unicode string.
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
