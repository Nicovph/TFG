"""Django session orchestration for Google OpenID Connect login."""

import uuid

from django.contrib.auth import login, logout
from django.http import HttpRequest

from backend.audit.models import SecurityEvent, SecurityEventType
from backend.audit.request_context import get_current_request_id

from .config import GoogleOIDCConfig, get_google_oidc_config
from .exceptions import (
    GoogleOIDCProviderError,
    GoogleOIDCStateError,
    GoogleOIDCTokenError,
)
from .flow_state import consume_google_oidc_state
from .provisioning import GoogleLoginResult, provision_user_from_claims
from .token_exchange import exchange_authorization_code_for_tokens
from .token_validation import validate_google_id_token


def complete_google_login(
    request: HttpRequest,
    *,
    code: str,
    state: str,
    config: GoogleOIDCConfig | None = None,
) -> GoogleLoginResult:
    """Complete the Google callback and authenticate the local Django session.

    Args:
        request: The callback request received by Django.
        code: The authorization code returned by Google.
        state: The state value returned by Google.
        config: Optional prevalidated Google OpenID Connect configuration.

    Returns:
        A GoogleLoginResult describing the authenticated user.

    Raises:
        Subclasses of GoogleOIDCError: If state validation, token exchange or 
            token validation fails.
    """
    if not code or not state:
        _record_failure(SecurityEventType.LOGIN_FAILED)
        raise GoogleOIDCStateError("Callback OAuth/OIDC incompleto.")

    oidc_config = config or get_google_oidc_config()

    try:
        flow_metadata = consume_google_oidc_state(
            request,
            state=state,
            config=oidc_config,
        )
    except GoogleOIDCStateError:
        _record_failure(SecurityEventType.LOGIN_FAILED)
        raise

    try:
        token_response = exchange_authorization_code_for_tokens(
            code=code,
            flow_metadata=flow_metadata,
            config=oidc_config,
        )
        claims = validate_google_id_token(
            id_token=str(token_response["id_token"]),
            expected_nonce=str(flow_metadata["nonce"]),
            expected_client_id=str(flow_metadata["client_id"]),
            config=oidc_config,
        )
    except GoogleOIDCProviderError:
        _record_failure(SecurityEventType.LOGIN_FAILED)
        raise
    except GoogleOIDCTokenError:
        _record_failure(SecurityEventType.IDENTITY_REJECTED)
        raise

    login_result = provision_user_from_claims(claims)
    # backend identifies the Django backend that authenticated the user and is used the ModelBackend 
    # because is created o recovered the user from the model CustomUser.
    login(
        request,
        login_result.user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    SecurityEvent.objects.record(
        event_type=SecurityEventType.LOGIN_SUCCEEDED,
        actor=login_result.user,
    )

    return login_result


def logout_current_user(request: HttpRequest) -> None:
    """End the current Django session without exposing tokens or profile data.

    Args:
        request: The authenticated request to log out.
    """
    user = request.user

    if user.is_authenticated:
        SecurityEvent.objects.record(
            event_type=SecurityEventType.LOGOUT,
            actor=user,
        )

    logout(request)


def build_session_status(request: HttpRequest) -> dict[str, bool]:
    """Build a minimized session status payload for the frontend.

    Args:
        request: The request whose authenticated user is inspected.

    Returns:
        A dictionary containing only whether the browser has an active session.
    """
    return {"authenticated": bool(request.user.is_authenticated)}


def _record_failure(event_type: str) -> None:
    """Record a minimized unauthenticated authentication failure event.

    Args:
        event_type: The structured security event type to record.
    """
    SecurityEvent.objects.record(
        event_type=event_type,
        request_id=get_current_request_id() or uuid.uuid4(),
    )
