"""Session-bound rate limiting for the Google OIDC login start endpoint."""

from rest_framework.request import Request
from rest_framework.views import APIView

from backend.throttles import PseudonymousRateThrottle


class GoogleLoginStartSessionThrottle(PseudonymousRateThrottle):
    """Limit login-flow creation per server-issued browser session."""

    key_salt = "accounts.google-login-start-session-throttle:v1"
    rate_setting = "GOOGLE_OIDC_LOGIN_ATTEMPTS_PER_MINUTE"
    rate_period = "minute"
    scope = "google_login_start_session"

    def get_subject(self, request: Request, view: APIView) -> str:
        """Return an existing or newly created server-side session key.

        Args:
            request: Anonymous or authenticated request starting Google login.
            view: Google login-start view protected by this throttle.

        Raises:
            RuntimeError: If the session backend fails to issue a session key.

        Returns:
            The opaque session key issued by Django.
        """
        session_key = request.session.session_key

        if session_key is None:
            # The OIDC flow already requires a session to bind its state; create
            # it before throttling so the first attempt is counted as well.
            request.session.create()
            session_key = request.session.session_key

        if session_key is None:
            raise RuntimeError("Django falló al crear una sesión del lado del servidor.")

        return session_key
