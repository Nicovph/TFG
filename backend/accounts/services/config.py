"""Configuration loading and validation for Google OpenID Connect."""

from dataclasses import dataclass # dataclass permits define oriented data classes.
from urllib.parse import urlparse

from django.conf import settings # Permits access to Django settings.

from .exceptions import GoogleOIDCConfigurationError


@dataclass(frozen=True) # frozen is used to create an immutable data class.
class GoogleOIDCConfig:
    """Validated Google OpenID Connect runtime settings.

    Args:
        client_id: OAuth 2.0 client identifier configured for this backend.
        client_secret: OAuth 2.0 client secret kept only on the backend.
        redirect_uri: Exact callback URI registered for the client.
        authorization_endpoint: Google authorization endpoint.
        token_endpoint: Google token endpoint.
        scopes: Minimal OpenID Connect scopes requested from Google.
        issuers: Accepted issuer identifiers for Google ID tokens.
        allowed_algorithms: Accepted JWT signing algorithms.
        flow_ttl_seconds: Temporary flow metadata lifetime.
        flow_cache_alias: Django cache alias used for temporary flow metadata.
        require_shared_flow_cache: Whether the flow cache must be shared.
        timeout_seconds: Outbound token-exchange timeout.
        max_iat_skew_seconds: Maximum tolerated future skew for ID token iat.
    """

    client_id: str
    client_secret: str
    redirect_uri: str
    authorization_endpoint: str
    token_endpoint: str
    scopes: tuple[str, ...]
    issuers: tuple[str, ...]
    allowed_algorithms: tuple[str, ...]
    flow_ttl_seconds: int
    flow_cache_alias: str
    require_shared_flow_cache: bool
    timeout_seconds: int
    max_iat_skew_seconds: int


def get_google_oidc_config() -> GoogleOIDCConfig:
    """Build a validated Google OpenID Connect configuration object.

    Returns:
        A validated GoogleOIDCConfig instance.

    Raises:
        GoogleOIDCConfigurationError: If any required setting is missing or
            unsafe for the configured environment.
    """
    try:
        config = GoogleOIDCConfig(
            client_id=_required_setting("GOOGLE_OIDC_CLIENT_ID"),
            client_secret=_required_setting("GOOGLE_OIDC_CLIENT_SECRET"),
            redirect_uri=_required_setting("GOOGLE_OIDC_REDIRECT_URI"),
            authorization_endpoint=str(settings.GOOGLE_OIDC_AUTHORIZATION_ENDPOINT), # Get from settings.py.
            token_endpoint=str(settings.GOOGLE_OIDC_TOKEN_ENDPOINT),
            scopes=tuple(settings.GOOGLE_OIDC_SCOPES),
            issuers=tuple(settings.GOOGLE_OIDC_ISSUERS),
            allowed_algorithms=tuple(settings.GOOGLE_OIDC_ALLOWED_ALGORITHMS),
            flow_ttl_seconds=int(settings.GOOGLE_OIDC_AUTH_FLOW_TTL_SECONDS),
            flow_cache_alias=_required_setting("GOOGLE_OIDC_FLOW_CACHE_ALIAS"),
            require_shared_flow_cache=settings.GOOGLE_OIDC_REQUIRE_SHARED_FLOW_CACHE,
            timeout_seconds=int(settings.GOOGLE_OIDC_TIMEOUT_SECONDS),
            max_iat_skew_seconds=int(settings.GOOGLE_OIDC_MAX_IAT_SKEW_SECONDS),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise GoogleOIDCConfigurationError(
            "La configuración de Google OIDC no es válida."
        ) from exc
    
    expected_issuers = {"https://accounts.google.com", "accounts.google.com"}

    _validate_endpoint_url(
        config.authorization_endpoint,
        setting_name="GOOGLE_OIDC_AUTHORIZATION_ENDPOINT",
    )
    _validate_endpoint_url(
        config.token_endpoint,
        setting_name="GOOGLE_OIDC_TOKEN_ENDPOINT",
    )
    _validate_redirect_uri(config.redirect_uri)

    if config.scopes != ("openid",):
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_SCOPES debe solicitar únicamente el scope openid."
        )

    if not config.flow_cache_alias:
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_FLOW_CACHE_ALIAS no puede estar vacío."
        )

    if not isinstance(config.require_shared_flow_cache, bool):
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_REQUIRE_SHARED_FLOW_CACHE debe ser un booleano."
        )
    
    if not config.allowed_algorithms:
        raise GoogleOIDCConfigurationError(
        "GOOGLE_OIDC_ALLOWED_ALGORITHMS no puede estar vacío."
    )

    if any(not isinstance(algorithm, str) for algorithm in config.allowed_algorithms):
        raise GoogleOIDCConfigurationError(
        "GOOGLE_OIDC_ALLOWED_ALGORITHMS debe contener cadenas de texto."
    )

    if config.allowed_algorithms != ("RS256",):
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_ALLOWED_ALGORITHMS debe permitir únicamente RS256."
        )
    
    if not config.issuers:
        raise GoogleOIDCConfigurationError(
        "GOOGLE_OIDC_ISSUERS no puede estar vacío."
    )
    
    if not set(config.issuers).issubset(expected_issuers):
        raise GoogleOIDCConfigurationError(
        "GOOGLE_OIDC_ISSUERS contiene emisores no permitidos para Google."
    )

    return config


def _required_setting(name: str) -> str:
    """Return a non-empty string setting.

    Args:
        name: The Django setting name to read.

    Returns:
        The stripped setting value.

    Raises:
        GoogleOIDCConfigurationError: If the setting is missing or empty.
    """
    # Get the value of the setting from Django settings, defaulting to an empty string if not found.
    value = getattr(settings, name, "") 

    if not isinstance(value, str) or not value.strip():
        raise GoogleOIDCConfigurationError(f"Falta la configuración {name}.")

    return value.strip()


def _validate_endpoint_url(url: str, *, setting_name: str) -> None:
    """Validate a configured provider endpoint URL.

    Args:
        url: The configured URL.
        setting_name: The setting name used in error messages.

    Raises:
        GoogleOIDCConfigurationError: If the URL is not an absolute HTTPS URL.
    """
    # Parse the URL producing an object with scheme, netloc, path, params, query, and fragment attributes.
    # Ejemplo: urlparse('https://www.example.com/path?query=1#fragment') returns ParseResult(scheme='https', netloc='www.example.com', path='/path', params='', query='query=1', fragment='fragment')
    parsed_url = urlparse(url)

    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.fragment:
        raise GoogleOIDCConfigurationError(
            f"{setting_name} debe ser una URL HTTPS absoluta sin fragmento."
        )
    
    if parsed_url.hostname not in {"accounts.google.com", "oauth2.googleapis.com"}:
        raise GoogleOIDCConfigurationError(
        f"{setting_name} debe apuntar a un endpoint oficial de Google."
        )


def _validate_redirect_uri(redirect_uri: str) -> None:
    """Validate the configured redirect URI for the OAuth/OIDC client.

    Args:
        redirect_uri: The callback URI configured for Google.

    Raises:
        GoogleOIDCConfigurationError: If the URI is not absolute or uses an
            unsafe scheme for the current environment.
    """
    parsed_uri = urlparse(redirect_uri)

    if not parsed_uri.scheme or not parsed_uri.netloc or parsed_uri.fragment:
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_REDIRECT_URI debe ser absoluta y no contener fragmento."
        )

    if parsed_uri.scheme == "https":
        return

    loopback_hosts = {"localhost", "127.0.0.1", "::1", "testserver"}

    if (
        settings.DEBUG
        and parsed_uri.scheme == "http"
        and parsed_uri.hostname in loopback_hosts
    ):
        return

    raise GoogleOIDCConfigurationError(
        "GOOGLE_OIDC_REDIRECT_URI debe usar HTTPS salvo en desarrollo local."
    )
