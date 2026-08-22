"""HTTP endpoints for backend-managed Google OpenID Connect sessions."""

from typing import Literal
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect # HttpRequest is used only for type hints.
from django.utils.cache import patch_cache_control # Used to prevent caching of sensitive responses (modifies Cache-Control header).
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie # This decorator forces Django to send the CSRF cookie in the response.
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .rate_limit_audit import record_google_login_rate_limit_best_effort
from .throttles import GoogleLoginStartSessionThrottle
from .services import (
    GoogleOIDCConfigurationError,
    GoogleOIDCError,
    GoogleOIDCProviderError,
    GoogleOIDCStateError,
    GoogleOIDCTokenError,
    build_session_status,
    complete_google_login, # Used to complete the Google OIDC flow and log in the user.
    create_google_authorization_url, # Used to start the Google OIDC flow.
    discard_google_oidc_state, # Used to discard the temporary flow state when the user cancels the flow.
    logout_current_user,
)

AuthStatusFragment = Literal["auth-error", "auth-rate-limited"]
_AUTH_ERROR_FRAGMENT: AuthStatusFragment = "auth-error"
_AUTH_RATE_LIMITED_FRAGMENT: AuthStatusFragment = "auth-rate-limited"

def _django_request(request: Request) -> HttpRequest:
    """Return the wrapped Django HttpRequest used by Django auth APIs.

    DRF documents that Request exposes standard HttpRequest attributes through
    composition. The authentication service still keeps a concrete HttpRequest
    type because Django's login() and logout() are Django auth APIs; this helper
    isolates the internal unwrap at the view boundary.

    Args:
        request: The Django REST Framework request wrapper.

    Returns:
        The underlying Django HttpRequest instance.
    """
    return request._request # Returns the Django request object wrapped by DRF's Request.


def _build_frontend_auth_return_url(
    request: HttpRequest,
    *,
    auth_status: AuthStatusFragment | None,
) -> str:
    """Build a safe SPA return URL for completed browser authentication flows.

    Args:
        request: The Django request that reached the callback endpoint.
        auth_status: Optional non-sensitive fragment that lets React show the
            appropriate authentication status screen.

    Returns:
        A validated absolute frontend URL with no query parameters.

    Raises:
        GoogleOIDCConfigurationError: If the configured frontend URL is unsafe.
    """
    configured_url = str(getattr(settings, "FRONTEND_AUTH_RETURN_URL", "")).strip()
    if configured_url:
        return_url = configured_url
    elif settings.DEBUG:
        # Local development may return to the origin that received the callback.
        return_url = request.build_absolute_uri("/")
    else:
        raise GoogleOIDCConfigurationError(
            "FRONTEND_AUTH_RETURN_URL es obligatorio fuera del entorno de desarrollo."
        )

    _validate_frontend_auth_return_url(return_url)

    if auth_status is not None:
        return f"{return_url}#{auth_status}"

    return return_url


def _validate_frontend_auth_return_url(return_url: str) -> None:
    """Validate that the configured frontend return URL cannot be an open redirect,
        ensuring that the return URL configured or provided by the user does not point 
        to an unauthorized external domain.

    Args:
        return_url: Absolute frontend URL configured by the deployment or
            derived from the callback request origin.

    Raises:
        GoogleOIDCConfigurationError: If the URL is not absolute, contains
            query or fragment data, or uses an unsafe scheme.
    """
    parsed_url = urlparse(return_url)

    if (
        not parsed_url.scheme
        or not parsed_url.netloc
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise GoogleOIDCConfigurationError(
            "FRONTEND_AUTH_RETURN_URL debe ser una URL absoluta sin query ni fragmento."
        )

    if parsed_url.username is not None or parsed_url.password is not None:
        raise GoogleOIDCConfigurationError(
            "FRONTEND_AUTH_RETURN_URL no puede contener credenciales."
        )

    if parsed_url.scheme == "https":
        return

    loopback_hosts = {"localhost", "127.0.0.1", "::1", "testserver"}

    if (
        settings.DEBUG
        and parsed_url.scheme == "http"
        and parsed_url.hostname in loopback_hosts
    ):
        return

    raise GoogleOIDCConfigurationError(
        "FRONTEND_AUTH_RETURN_URL debe usar HTTPS salvo en desarrollo local."
    )


def _redirect_to_frontend_auth_status(
    request: HttpRequest,
    *,
    auth_status: AuthStatusFragment | None,
) -> HttpResponseRedirect:
    """Redirect the browser back to React without exposing OAuth/OIDC artifacts.

    Args:
        request: The Django request that reached the callback endpoint.
        auth_status: Optional non-sensitive status that React should show.

    Returns:
        A no-store redirect response to the frontend.
    """
    response = HttpResponseRedirect(
        _build_frontend_auth_return_url(
            request,
            auth_status=auth_status,
        )
    )
    patch_cache_control(response, no_store=True)
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([GoogleLoginStartSessionThrottle])
def _google_login_start(request: Request) -> HttpResponseRedirect | Response:
    """Start the backend-managed Google OpenID Connect authorization flow.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A redirect response to Google, a generic redirect to React when the
        provider is unavailable, or a JSON error if React redirection is unsafe.
    """
    django_request = _django_request(request)

    try:
        authorization_url = create_google_authorization_url(django_request)
    except GoogleOIDCConfigurationError:
        try:
            return _redirect_to_frontend_auth_status(
                django_request,
                auth_status=_AUTH_ERROR_FRAGMENT,
            )
        # If the frontend redirection failed, continue to next part.
        except GoogleOIDCConfigurationError:
            pass

        # If the frontend redirection does not work, it is returned a clear JSON error.
        response = Response(
            {"error": "authentication_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) # Returns a 503 error because the backend is not configured.
        return response

    return HttpResponseRedirect(authorization_url)


@never_cache
def google_login_start(request: HttpRequest) -> HttpResponseRedirect | Response:
    """Return throttled browser login attempts to an accessible React screen.

    Args:
        request: The raw Django request received from the user's browser.

    Returns:
        The normal DRF login-start response, or a no-store frontend redirect
        carrying only a non-sensitive rate-limit fragment.
    """
    response = _google_login_start(request)

    if response.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
        return response

    retry_after = response.get("Retry-After", "")
    record_google_login_rate_limit_best_effort(
        retry_after_seconds=int(retry_after) if retry_after.isdecimal() else 60,
    )

    try:
        return _redirect_to_frontend_auth_status(
            request,
            auth_status=_AUTH_RATE_LIMITED_FRAGMENT,
        )
    except GoogleOIDCConfigurationError:
        # Preserve DRF's safe 429 response if the configured frontend URL is invalid.
        return response


@api_view(["GET"])
@permission_classes([AllowAny])
def google_login_callback(request: Request) -> HttpResponseRedirect | Response:
    """Handle the Google callback without exposing OAuth/OIDC artifacts.

    Args:
        request: The callback request received by Django REST Framework.

    Returns:
        A redirect to React after processing the callback, or a generic JSON
        error only if backend redirect configuration is invalid.
    """
    django_request = _django_request(request)
    provider_error = request.query_params.get("error", "")
    state = request.query_params.get("state", "") # It is necessary to get the state even if there is an error
                                                  # in the provider because it can return the state.

    if provider_error:
        discard_google_oidc_state(django_request, state=state)
        try:
            return _redirect_to_frontend_auth_status(
                django_request,
                auth_status=_AUTH_ERROR_FRAGMENT,
            )
        except GoogleOIDCConfigurationError:
            response = Response(
                {"error": "authentication_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            patch_cache_control(response, no_store=True)
            return response

    code = request.query_params.get("code", "")

    try:
        complete_google_login(
            django_request,
            code=code,
            state=state,
        )
    except GoogleOIDCStateError:
        authentication_failed = True
    except GoogleOIDCProviderError:
        authentication_failed = True
    except GoogleOIDCTokenError:
        authentication_failed = True
    except GoogleOIDCConfigurationError:
        authentication_failed = True
    except GoogleOIDCError:
        authentication_failed = True
    else:
        authentication_failed = False

    try:
        return _redirect_to_frontend_auth_status(
            django_request,
            auth_status=_AUTH_ERROR_FRAGMENT if authentication_failed else None,
        )
    except GoogleOIDCConfigurationError:
        response = Response(
            {"error": "authentication_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        patch_cache_control(response, no_store=True)
        return response


# This decorator is used here to ensure the frontend receives the CSRF cookie during the first
#  interaction, avoiding subsequent issues when making requests that require CSRF protection.
@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
# This view is called by React to know wether the user is already autheticated.
def session_status(request: Request) -> Response:
    """Return the current browser session authentication status.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A minimized JSON response without local identifiers or profile claims.
    """
    response = Response(build_session_status(_django_request(request)))
    patch_cache_control(response, no_store=True)
    return response


@api_view(["POST"]) # GET would be more insecure because it could be activated links, images...
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    """Log out the current authenticated Django session.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A minimized JSON response confirming that the browser is unauthenticated.
    """
    logout_current_user(_django_request(request))
    response = Response({"authenticated": False})
    patch_cache_control(response, no_store=True)
    return response
