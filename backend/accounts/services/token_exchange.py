"""Token endpoint exchange for Google OpenID Connect callbacks."""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping

from .config import GoogleOIDCConfig
from .exceptions import GoogleOIDCProviderError


def exchange_authorization_code_for_tokens(
    *,
    code: str,
    flow_metadata: Mapping[str, object],
    config: GoogleOIDCConfig,
) -> Mapping[str, object]:
    """Exchange an authorization code for Google OAuth/OIDC tokens.

    Args:
        code: The one-time authorization code returned by Google.
        flow_metadata: Temporary backend metadata for this OAuth/OIDC flow.
        config: The validated Google OpenID Connect configuration.

    Returns:
        The parsed token endpoint JSON response.

    Raises:
        GoogleOIDCProviderError: If the token endpoint rejects the request or
            returns an invalid payload.
    """
    code_verifier = flow_metadata.get("code_verifier")

    if not isinstance(code_verifier, str) or not code_verifier:
        raise GoogleOIDCProviderError("Falta el code_verifier PKCE.")

    # urlencode converts a dict in a form chain.
    request_body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    token_request = urllib.request.Request(
        config.token_endpoint,
        data=request_body,
        # A JSON response is expected and Content-Type defines the data format expected (form) by the token endpoint.
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        # It prevents authentication metadata from being exposed in server logs or browser history, unlike the GET method.
        method="POST",
    )

    try:
        # Sends the request. With ensures that the response is closed correctly upon completion.
        with urllib.request.urlopen(
            token_request,
            timeout=config.timeout_seconds,
        ) as token_response:
            # Reads only 65536 bytes in the body response, avoiding to read arbitrarily large responses in memory.
            raw_body = token_response.read(65536)
            # URLError includes conection errors, DNS, TLS...
    except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise GoogleOIDCProviderError(
            "No se pudo completar el canje de código OAuth/OIDC."
        ) from exc

    try:
        # Converts the bytes to UTF text and whit json.loads, the parsed_body to a dict.
        parsed_body = json.loads(raw_body.decode("utf-8"))
        # UnicodeDecodeError: the response is not correctly encoded as UTF-8. JSONDecodeError: the response is not valid JSON.
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoogleOIDCProviderError(
            "La respuesta del proveedor OAuth/OIDC no es JSON válido."
        ) from exc

    if not isinstance(parsed_body, Mapping):
        raise GoogleOIDCProviderError(
            "La respuesta del proveedor OAuth/OIDC tiene un formato no válido."
        )

    id_token = parsed_body.get("id_token")
    access_token = parsed_body.get("access_token")
    token_type = parsed_body.get("token_type")

    if not isinstance(id_token, str) or not id_token:
        raise GoogleOIDCProviderError("El proveedor no devolvió un ID token.")

    if not isinstance(access_token, str) or not access_token:
        raise GoogleOIDCProviderError("El proveedor no devolvió un access token.")

    if token_type != "Bearer":
        raise GoogleOIDCProviderError("El tipo de token devuelto no es válido.")

    return parsed_body
