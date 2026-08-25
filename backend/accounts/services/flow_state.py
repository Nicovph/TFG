"""Temporary state storage for the Google OpenID Connect login flow."""

import secrets # Is used to generate secure random values.
import urllib.parse
from collections.abc import Mapping

from django.conf import settings
from django.core.cache import (
    BaseCache,
    InvalidCacheBackendError,
    caches,
) # Imports the Django cache framework for temporary storage of OAuth/OIDC flow state.
from django.core.cache.backends.dummy import DummyCache
from django.core.cache.backends.locmem import LocMemCache
from django.core.signing import salted_hmac # salted_hmac is used to create keyed digests.
from django.http import HttpRequest
from django.utils import timezone
# Is used to compare sensitive values in a way that prevents timing attacks.
from django.utils.crypto import constant_time_compare 

from .config import GoogleOIDCConfig, get_google_oidc_config
from .exceptions import (
    GoogleOIDCConfigurationError,
    GoogleOIDCError,
    GoogleOIDCStateError,
)
from .pkce import (
    PKCE_CODE_CHALLENGE_METHOD,
    create_pkce_code_challenge,
    create_pkce_code_verifier,
)

# Prefix for cache keys used to store temporary Google OIDC flow state.
GOOGLE_OIDC_CACHE_PREFIX = "accounts:google-oidc:"

# Cache backends that cannot share OAuth/OIDC flow metadata across processes.
_UNSHARED_FLOW_CACHE_BACKEND_TYPES = (DummyCache, LocMemCache)


def create_google_authorization_url(
    request: HttpRequest,
    *,
    config: GoogleOIDCConfig | None = None,
) -> str:
    """Create a Google authorization URL and temporary backend flow metadata.

    Args:
        request: The incoming Django request whose session binds the flow.
        config: Optional prevalidated Google OpenID Connect configuration.

    Returns:
        The Google authorization URL to redirect the browser to.

    Raises:
        GoogleOIDCConfigurationError: If Google OIDC settings are incomplete.
    """
    # If config is None, it is used get_google_oidc_config() to retrieve the validated Google OIDC configuration.
    oidc_config = config or get_google_oidc_config()
    flow_cache = _get_google_oidc_flow_cache(oidc_config)
    # Ensures that the request has a server-side Django session key (random 32 characters string that identifies the user's session).
    session_key = _ensure_session_key(request)
    # Generates a secure random value of 32 characters encoded in base64url.
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = create_pkce_code_verifier()
    code_challenge = create_pkce_code_challenge(code_verifier)
    # Get the current moment in time as a Unix timestamp.
    now = int(timezone.now().timestamp())

    # Sotre the temporary flow metadata in the Django cache with a timeout defined by oidc_config.flow_ttl_seconds.
    metadata = {
        "client_id": oidc_config.client_id,
        "redirect_uri": oidc_config.redirect_uri,
        "session_key_hash": _session_key_hash(session_key), # Store a keyed digest of the session key.
        "nonce": nonce,
        "code_verifier": code_verifier,
        "code_challenge_method": PKCE_CODE_CHALLENGE_METHOD,
        "created_at": now,
        "expires_at": now + oidc_config.flow_ttl_seconds,
    }
    # Stores the metadata in the cache using a cache key derived from a keyed digest of the state value.
    flow_cache.set(
        _state_cache_key(state),
        metadata,
        timeout=oidc_config.flow_ttl_seconds,
    )

    # Builds the query string (begins with a question mark) for the Google authorization URL using the stored metadata and OIDC configuration.
    query = urllib.parse.urlencode(
        {
            "client_id": oidc_config.client_id,
            "response_type": "code", # To be used in the Authorization Code Flow.
            "scope": " ".join(oidc_config.scopes),
            "redirect_uri": oidc_config.redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": PKCE_CODE_CHALLENGE_METHOD,
        }
    )
    return f"{oidc_config.authorization_endpoint}?{query}"


# It is used in the callback.
def consume_google_oidc_state(
    request: HttpRequest,
    *,
    state: str,
    config: GoogleOIDCConfig,
) -> Mapping[str, object]:
    """Load, validate and remove one temporary OAuth/OIDC flow record.

    Args:
        request: The callback request carrying the browser session.
        state: The state value returned by Google.
        config: The validated Google OpenID Connect configuration.

    Returns:
        The temporary flow metadata stored before redirecting to Google.

    Raises:
        GoogleOIDCStateError: If the state is missing, expired, reused or not
            bound to the current browser session.
    """
    if not state:
        raise GoogleOIDCStateError("Falta el parámetro state.")

    flow_cache = _get_google_oidc_flow_cache(config)
    # Calculates the cache key for the given state.
    cache_key = _state_cache_key(state)
    # Retrives the temporary flow metadata from the cache using the calculated HMAC cache key.
    metadata = flow_cache.get(cache_key)

    if not isinstance(metadata, Mapping):
        raise GoogleOIDCStateError("El parámetro state no es válido.")

    now = int(timezone.now().timestamp())
    expires_at = metadata.get("expires_at")

    if not isinstance(expires_at, int) or expires_at <= now:
        flow_cache.delete(cache_key)
        raise GoogleOIDCStateError("El parámetro state ha caducado.")

    # Obtains the Django session from the callback.
    session_key = request.session.session_key

    if not session_key:
        raise GoogleOIDCStateError(
            "No existe una sesión iniciada para el callback de autenticación."
        )

    expected_session_hash = metadata.get("session_key_hash")

    # Validates that the session hash stored matches the current session hash.
    if not isinstance(expected_session_hash, str) or not constant_time_compare(
        expected_session_hash,
        _session_key_hash(session_key),
    ):
        raise GoogleOIDCStateError(
            "El parámetro state no pertenece a esta sesión."
        )

    if metadata.get("client_id") != config.client_id:
        flow_cache.delete(cache_key)
        raise GoogleOIDCStateError("Cliente OAuth/OIDC inconsistente.")

    if metadata.get("redirect_uri") != config.redirect_uri:
        flow_cache.delete(cache_key)
        raise GoogleOIDCStateError("URI de redirección OAuth/OIDC incoherente.")

    # Prevents reuse of the state.
    flow_cache.delete(cache_key)
    return metadata


def discard_google_oidc_state(request: HttpRequest, *, state: str) -> None:
    """Best-effort cleanup for an OAuth/OIDC flow that ended with provider error.

    Args:
        request: The callback request carrying the browser session.
        state: The state value returned by Google, if any.
    """
    if not state:
        return

    try:
        # Consume the state to remove it from the cache and validate it.
        consume_google_oidc_state(
            request,
            state=state,
            config=get_google_oidc_config(),
        )
    except GoogleOIDCError:
        return


def _get_google_oidc_flow_cache(config: GoogleOIDCConfig) -> BaseCache:
    """Return the configured cache for temporary Google OIDC flow state.

    Args:
        config: The validated Google OpenID Connect configuration.

    Returns:
        The Django cache backend selected for temporary flow metadata.

    Raises:
        GoogleOIDCConfigurationError: If the cache alias is not configured or
            points to a backend that cannot satisfy the shared-cache policy.
    """
    try:
        flow_cache = caches[config.flow_cache_alias]
    except InvalidCacheBackendError as exc:
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_FLOW_CACHE_ALIAS debe apuntar a una caché configurada."
        ) from exc

    _validate_google_oidc_flow_cache(flow_cache, config=config)
    return flow_cache


def _validate_google_oidc_flow_cache(
    flow_cache: BaseCache,
    *,
    config: GoogleOIDCConfig,
) -> None:
    """Reject non-shared cache backends when the OIDC flow requires sharing.

    Args:
        flow_cache: The Django cache backend selected by configuration.
        config: The validated Google OpenID Connect configuration.

    Raises:
        GoogleOIDCConfigurationError: If a shared cache is required but the
            selected backend is local to one process or does not store values.
    """
    if not config.require_shared_flow_cache:
        return

    if isinstance(flow_cache, _UNSHARED_FLOW_CACHE_BACKEND_TYPES):
        raise GoogleOIDCConfigurationError(
            "GOOGLE_OIDC_FLOW_CACHE_ALIAS debe apuntar a una caché compartida "
            "cuando GOOGLE_OIDC_REQUIRE_SHARED_FLOW_CACHE está activo."
        )


def _ensure_session_key(request: HttpRequest) -> str:
    """Ensure the request has a server-side Django session key.

    Args:
        request: The request whose session should bind the OAuth/OIDC flow.

    Returns:
        The existing or newly-created session key.
    """
    if request.session.session_key is None:
        request.session.create()

    return str(request.session.session_key)


def _state_cache_key(state: str) -> str:
    """Build a cache key without storing the raw state value in the key.

    Args:
        state: The OAuth/OIDC state value.

    Returns:
        A cache key derived from a keyed digest of the state.
    """
    # Is used a keyed digest state to prevent attackers from getting the satate.
    # accounts.google_oidc.state is used as the key salt to ensure that the digest is unique to this application and purpose.
    digest = salted_hmac(
        "accounts.google_oidc.state",
        state,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
    return f"{GOOGLE_OIDC_CACHE_PREFIX}{digest}"


def _session_key_hash(session_key: str) -> str:
    """Return a keyed digest of the Django session key for flow binding.

    Args:
        session_key: The Django session key to bind to the OAuth/OIDC flow.

    Returns:
        A keyed SHA-256 digest of the session key.
    """
    return salted_hmac(
        "accounts.google_oidc.session",
        session_key,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
