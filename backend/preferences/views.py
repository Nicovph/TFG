"""Authenticated HTTP endpoints for user-owned preferences."""

from django.utils.cache import patch_cache_control
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .serializers import UserPreferencesSerializer
from .services import get_user_preferences, update_user_preferences


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
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

    response = Response(UserPreferencesSerializer(preferences).data)
    patch_cache_control(response, no_store=True)
    return response
