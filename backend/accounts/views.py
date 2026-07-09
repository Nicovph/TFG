"""HTTP endpoints for backend-managed Google OpenID Connect sessions."""

from django.http import HttpRequest, HttpResponseRedirect # HttpRequest is used only for type hints.
from django.utils.cache import patch_cache_control # Used to prevent caching of sensitive responses (modifies Cache-Control header).
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

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


@api_view(["GET"])
@permission_classes([AllowAny])
def google_login_start(request: Request) -> HttpResponseRedirect | Response:
    """Start the backend-managed Google OpenID Connect authorization flow.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A redirect response to Google, or a generic JSON error if the backend is
        not configured.
    """
    try:
        authorization_url = create_google_authorization_url(_django_request(request))
    except GoogleOIDCConfigurationError:
        response = Response(
            {"error": "authentication_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) # Returns a 503 error because the backend is not configured.
        patch_cache_control(response, no_store=True)# Prevents caching of the error response.
        return response

    response = HttpResponseRedirect(authorization_url)
    patch_cache_control(response, no_store=True) # Prevents caching of the redirect response to avoid
                                                 # exposing sensitive information (state, nonce and code_challenge).
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def google_login_callback(request: Request) -> Response:
    """Handle the Google callback without exposing OAuth/OIDC artifacts.

    Args:
        request: The callback request received by Django REST Framework.

    Returns:
        A minimized JSON response that only indicates whether authentication
        succeeded.
    """
    provider_error = request.query_params.get("error", "")
    state = request.query_params.get("state", "") # It is necessary to get the state even if there is an error
                                                  # in the provider because it can return the state.

    if provider_error:
        discard_google_oidc_state(_django_request(request), state=state)
        response = Response(
            {"error": "authentication_canceled"},
            status=status.HTTP_400_BAD_REQUEST,
        ) # Returns a generic errorto avoid the exposition of provider details or parameters that can be manipulated.
        patch_cache_control(response, no_store=True)
        return response

    code = request.query_params.get("code", "")

    try:
        complete_google_login(
            _django_request(request),
            code=code,
            state=state,
        )
    except GoogleOIDCStateError:
        response = Response(
            {"error": "invalid_authentication_callback"},
            status=status.HTTP_400_BAD_REQUEST,
        ) # Returns a 400 error because the received callback is invalid.
    except GoogleOIDCProviderError:
        response = Response(
            {"error": "authentication_provider_unavailable"},
            status=status.HTTP_502_BAD_GATEWAY,
        ) # Returns a 502 error because the provider is unavailable or returned an error.
    except GoogleOIDCTokenError:
        response = Response(
            {"error": "authentication_rejected"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except GoogleOIDCConfigurationError:
        response = Response(
            {"error": "authentication_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) # Returns a 503 error because the backend is misconfigured.
    except GoogleOIDCError:
        response = Response(
            {"error": "authentication_failed"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    else:
        response = Response({"authenticated": True})

    patch_cache_control(response, no_store=True)
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
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
