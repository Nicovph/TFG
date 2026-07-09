"""Shared helpers for account and Google OpenID Connect tests."""

import base64
import json

from django.utils import timezone


def base64url_json(payload: dict[str, object]) -> str:
    """Encode a JSON object as a base64url JWT segment for tests.

    Args:
        payload: The JSON-compatible payload to encode.

    Returns:
        A base64url-encoded string without padding.
    """
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def fake_jwt(*, algorithm: str = "RS256") -> str:
    """Build a compact fake JWT whose signature is supplied by mocks.

    Args:
        algorithm: The JWT alg header value to encode.

    Returns:
        A compact JWT string with a placeholder signature.
    """
    # kid is an optional parameter in the header of a JWT that uniquely identifies the cryptographic key used to sign the token.
    header = base64url_json(
        {
            "alg": algorithm,
            "kid": "test-key",
            "typ": "JWT",
        }
    )
    payload = base64url_json({"test": True})
    return f"{header}.{payload}.signature"


def valid_claims(
    *,
    nonce: str,
    subject: str = "google-subject-flow",
) -> dict[str, object]:
    """Build validated Google ID token claims for tests.

    Args:
        nonce: The expected nonce to include in the claims.
        subject: The Google OIDC subject to include in the claims.

    Returns:
        A dictionary with required OIDC claims.
    """
    now = int(timezone.now().timestamp())
    return {
        "iss": "https://accounts.google.com",
        "aud": "client-id.apps.googleusercontent.com",
        "sub": subject,
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
    }
