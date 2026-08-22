"""Authenticated write throttles for user-owned preferences."""

from uuid import UUID

from rest_framework.request import Request
from rest_framework.views import APIView

from backend.throttles import PseudonymousRateThrottle


class _PreferenceUpdateThrottle(PseudonymousRateThrottle):
    """Count only PATCH attempts under the authenticated user's UUID."""

    key_salt = "preferences.update-throttle:v1"

    def get_subject(self, request: Request, view: APIView) -> str | None:
        """Return the authenticated UUID only for preference updates.

        Args:
            request: Authenticated preferences request being checked.
            view: Preferences view protected by this throttle.

        Raises:
            RuntimeError: If an authenticated PATCH has a non-UUID primary key.

        Returns:
            A canonical UUID value for PATCH, or None for other methods.
        """
        if request.method != "PATCH":
            return None

        user_id = request.user.pk

        if not isinstance(user_id, UUID):
            raise RuntimeError(
                "Las actualizaciones de preferencias autenticadas requieren una " \
                "clave primaria de usuario de tipo UUID."
            )

        # UUID.hex provides a compact and stable canonical representation.
        return user_id.hex


class PreferenceUpdateBurstThrottle(_PreferenceUpdateThrottle):
    """Limit short bursts of authenticated preference updates."""

    rate_setting = "PREFERENCES_UPDATE_ATTEMPTS_PER_MINUTE"
    rate_period = "minute"
    scope = "preference_update_burst"


class PreferenceUpdateSustainedThrottle(_PreferenceUpdateThrottle):
    """Limit sustained authenticated preference updates."""

    rate_setting = "PREFERENCES_UPDATE_ATTEMPTS_PER_DAY"
    rate_period = "day"
    scope = "preference_update_sustained"
