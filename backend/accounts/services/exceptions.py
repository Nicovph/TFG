"""Controlled exceptions for Google OpenID Connect account services."""


class GoogleOIDCError(Exception):
    """Base exception for controlled Google OpenID Connect failures."""


class GoogleOIDCConfigurationError(GoogleOIDCError):
    """Raised when the Google OpenID Connect backend is not configured safely."""


class GoogleOIDCStateError(GoogleOIDCError):
    """Raised when the callback does not match a valid temporary login flow."""


class GoogleOIDCProviderError(GoogleOIDCError):
    """Raised when Google cannot exchange an authorization code for tokens."""


class GoogleOIDCTokenError(GoogleOIDCError):
    """Raised when the received ID token is missing or fails validation."""
