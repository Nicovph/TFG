"""Authenticated HTTP endpoints for user-owned preferences."""

from django.views.decorators.cache import never_cache
from rest_framework.decorators import (
    api_view,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .serializers import UserPreferencesSerializer
from .services import get_user_preferences, update_user_preferences
from .throttles import (
    PreferenceUpdateBurstThrottle,
    PreferenceUpdateSustainedThrottle,
)


@never_cache
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@throttle_classes([
    PreferenceUpdateBurstThrottle,
    PreferenceUpdateSustainedThrottle,
])
def user_preferences(request: Request) -> Response:
    """Retrieve or update preferences for the authenticated session user.

    Args:
        request: The request whose validated session identifies the owner.

    Returns:
        A no-store response containing only the five preference values.
    """
    if request.method == "PATCH":
        input_serializer = UserPreferencesSerializer(
            data=request.data,
            partial=True,
        )
        input_serializer.is_valid(raise_exception=True)
        preferences = update_user_preferences(
            user=request.user,
            changes=input_serializer.validated_data,
        )
    else:
        preferences = get_user_preferences(user=request.user)

    return Response(UserPreferencesSerializer(preferences).data)
