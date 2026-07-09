"""Google ID token validation helpers for OpenID Connect login."""

import base64
import binascii
import json
from typing import Any, Mapping

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from backend.accounts.models import google_subject_validator

from .config import GoogleOIDCConfig
from .exceptions import GoogleOIDCConfigurationError, GoogleOIDCTokenError


def validate_google_id_token(
    *,
    id_token: str,
    expected_nonce: str,
    expected_client_id: str,
    config: GoogleOIDCConfig,
) -> Mapping[str, object]:
    """Validate a Google ID token signature, algorithm and required claims.

    Args:
        id_token: The compact JWT returned by Google.
        expected_nonce: The nonce generated before redirecting to Google.
        expected_client_id: The OAuth client identifier that started the flow.
        config: The validated Google OpenID Connect configuration.

    Returns:
        The validated ID token claims.

    Raises:
        GoogleOIDCTokenError: If the token header, signature or claims fail
            validation.
    """
    header = decode_unverified_jwt_header(id_token)
    algorithm = header.get("alg")

    if not isinstance(algorithm, str) or algorithm not in config.allowed_algorithms:
        raise GoogleOIDCTokenError("Algoritmo JWT no permitido.")

    claims = verify_google_id_token_signature(
        id_token=id_token,
        audience=expected_client_id,
    )

    issuer = _required_string_claim(claims, "iss")

    if issuer not in config.issuers:
        raise GoogleOIDCTokenError("Issuer OIDC no permitido.")

    _validate_audience(claims, expected_client_id=expected_client_id)
    _validate_expiry_and_issued_at(
        claims,
        max_iat_skew_seconds=config.max_iat_skew_seconds,
    )

    nonce = _required_string_claim(claims, "nonce")

    if not constant_time_compare(nonce, expected_nonce):
        raise GoogleOIDCTokenError("Nonce OIDC no válido.")

    subject = _required_string_claim(claims, "sub")

    try:
        google_subject_validator(subject)
    except ValidationError as exc:
        raise GoogleOIDCTokenError("Subject OIDC no válido.") from exc

    return claims


def decode_unverified_jwt_header(id_token: str) -> Mapping[str, object]:
    """Decode the JWT header before signature verification.

    Args:
        id_token: The compact JWT string to inspect.

    Returns:
        The decoded JWT header.

    Raises:
        GoogleOIDCTokenError: If the token does not contain a valid JSON header.
    """
    parts = id_token.split(".")

    if len(parts) != 3:
        raise GoogleOIDCTokenError("Formato JWT no válido.")

    try:
        decoded = _decode_base64url_json(parts[0])
    except (
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise GoogleOIDCTokenError("Cabecera JWT no válida.") from exc

    if not isinstance(decoded, Mapping):
        raise GoogleOIDCTokenError("Cabecera JWT no válida.")

    return decoded


def verify_google_id_token_signature(
    *,
    id_token: str,
    audience: str,
) -> Mapping[str, object]:
    """Verify the Google ID token with the maintained Google Auth library.

    Args:
        id_token: The compact JWT returned by Google.
        audience: The expected OAuth client identifier.

    Returns:
        The verified ID token claims.

    Raises:
        GoogleOIDCConfigurationError: If the verification dependency is missing.
        GoogleOIDCTokenError: If Google Auth rejects the ID token.
    """
    try:
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:
        raise GoogleOIDCConfigurationError(
            "Falta la dependencia google-auth para validar ID tokens."
        ) from exc

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token,
            GoogleAuthRequest(),
            audience,
        )
    except ValueError as exc:
        raise GoogleOIDCTokenError("Firma o claims del ID token no válidos.") from exc

    if not isinstance(claims, Mapping):
        raise GoogleOIDCTokenError("Claims del ID token no válidos.")

    return claims


def _decode_base64url_json(segment: str) -> Any:
    """Decode a base64url JWT segment as JSON.

    Args:
        segment: The base64url-encoded JWT segment.

    Returns:
        The decoded JSON value.

    Raises:
        ValueError: If the segment cannot be base64url-decoded.
        UnicodeDecodeError: If the decoded bytes are not UTF-8.
        json.JSONDecodeError: If the decoded text is not JSON.
    """
    # The padding is calculated because the base64 decode needs the length to be a multiple of 4.
    padding = "=" * (-len(segment) % 4)
    # encode("ascii") converts to bytes.
    decoded_bytes = base64.urlsafe_b64decode((segment + padding).encode("ascii"))
    # decode converts the bytes to text (JSON string).
    return json.loads(decoded_bytes.decode("utf-8"))


def _required_string_claim(
    claims: Mapping[str, object],
    claim_name: str,
) -> str:
    """Read a required string claim from a validated ID token.

    Args:
        claims: The validated ID token claims.
        claim_name: The claim name to read.

    Returns:
        The non-empty claim value.

    Raises:
        GoogleOIDCTokenError: If the claim is missing or not a string.
    """
    value = claims.get(claim_name)

    if not isinstance(value, str) or not value:
        raise GoogleOIDCTokenError(f"Claim OIDC obligatorio ausente: {claim_name}.")

    return value


def _required_int_claim(claims: Mapping[str, object], claim_name: str) -> int:
    """Read a required integer claim from a validated ID token.

    Args:
        claims: The validated ID token claims.
        claim_name: The claim name to read.

    Returns:
        The integer claim value.

    Raises:
        GoogleOIDCTokenError: If the claim is missing or not an integer.
    """
    value = claims.get(claim_name)

    if type(value) is not int:
        raise GoogleOIDCTokenError(f"Claim OIDC obligatorio ausente: {claim_name}.")

    return value


def _validate_audience(
    claims: Mapping[str, object],
    *,
    expected_client_id: str,
) -> None:
    """Validate the audience and authorized presenter claims.

    Args:
        claims: The validated ID token claims.
        expected_client_id: The OAuth client identifier that started the flow.

    Raises:
        GoogleOIDCTokenError: If the audience or authorized presenter is not
            the configured backend client.
    """
    audience = claims.get("aud")

    # aud can be a str (token for one audience) or string array (token for multiple audiences).
    if isinstance(audience, str):
        # Converts the str in a one element list.
        audiences = [audience]
    elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
        audiences = audience
    else:
        raise GoogleOIDCTokenError("Audience OIDC no válida.")

    if expected_client_id not in audiences:
        raise GoogleOIDCTokenError("Audience OIDC no coincide.")

    authorized_party = claims.get("azp")

    if authorized_party is not None and authorized_party != expected_client_id:
        raise GoogleOIDCTokenError("Authorized party OIDC no coincide.")

    if len(audiences) > 1 and authorized_party != expected_client_id:
        raise GoogleOIDCTokenError("Authorized party OIDC no coincide.")


def _validate_expiry_and_issued_at(
    claims: Mapping[str, object],
    *,
    max_iat_skew_seconds: int,
) -> None:
    """Validate the ID token lifetime claims.

    Args:
        claims: The validated ID token claims.
        max_iat_skew_seconds: Maximum tolerated future skew for iat.

    Raises:
        GoogleOIDCTokenError: If exp is expired or iat is unexpectedly future.
    """
    now = int(timezone.now().timestamp())
    expires_at = _required_int_claim(claims, "exp")
    issued_at = _required_int_claim(claims, "iat")

    if expires_at <= now:
        raise GoogleOIDCTokenError("ID token caducado.")

    if issued_at > now + max_iat_skew_seconds:
        raise GoogleOIDCTokenError("ID token emitido en el futuro.")
