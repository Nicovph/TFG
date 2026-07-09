"""URL routes for backend-managed account authentication."""

from django.urls import path

from . import views


urlpatterns = [
    path(
        "auth/google/start/",
        views.google_login_start,
        name="google-login-start",
    ),
    # URL to which Google will redirect the user after they approve or deny the authorization request.
    path(
        "auth/google/callback/",
        views.google_login_callback,
        name="google-login-callback",
    ),
    # URL to check the current session status.
    path(
        "auth/session/",
        views.session_status,
        name="session-status",
    ),
    path(
        "auth/logout/",
        views.logout_view,
        name="auth-logout",
    ),
]
