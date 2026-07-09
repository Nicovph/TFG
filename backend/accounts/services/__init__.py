"""Public service interface for Google OpenID Connect account workflows."""

from .config import GoogleOIDCConfig, get_google_oidc_config
from .exceptions import (
    GoogleOIDCConfigurationError,
    GoogleOIDCError,
    GoogleOIDCProviderError,
    GoogleOIDCStateError,
    GoogleOIDCTokenError,
)
from .flow_state import (
    create_google_authorization_url,
    consume_google_oidc_state,
    discard_google_oidc_state,
)
from .pkce import (
    PKCE_CODE_CHALLENGE_METHOD,
    create_pkce_code_challenge,
    create_pkce_code_verifier,
)
from .provisioning import (
    GoogleLoginResult,
    promote_user,
    provision_user_from_claims,
)
from .session import (
    build_session_status,
    complete_google_login,
    logout_current_user,
)
from .token_exchange import exchange_authorization_code_for_tokens
from .token_validation import (
    decode_unverified_jwt_header,
    validate_google_id_token,
    verify_google_id_token_signature,
)

# Defines the public interface of this package for `from backend.accounts.services import *`.
__all__ = [
    "GoogleLoginResult",
    "GoogleOIDCConfig",
    "GoogleOIDCConfigurationError",
    "GoogleOIDCError",
    "GoogleOIDCProviderError",
    "GoogleOIDCStateError",
    "GoogleOIDCTokenError",
    "PKCE_CODE_CHALLENGE_METHOD",
    "build_session_status",
    "complete_google_login",
    "consume_google_oidc_state",
    "create_google_authorization_url",
    "create_pkce_code_challenge",
    "create_pkce_code_verifier",
    "decode_unverified_jwt_header",
    "discard_google_oidc_state",
    "exchange_authorization_code_for_tokens",
    "get_google_oidc_config",
    "logout_current_user",
    "promote_user",
    "provision_user_from_claims",
    "validate_google_id_token",
    "verify_google_id_token_signature",
]
