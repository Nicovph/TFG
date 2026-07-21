"""Transactional domain services for user-owned preferences."""

from collections.abc import Mapping

from django.db import transaction

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEvent, SecurityEventType

from .models import UserPreferences

UPDATABLE_PREFERENCE_FIELDS = frozenset(
    {
        "interpretation_detail",
        "show_content_warnings",
        "show_offensive_language",
        "theme",
        "visual_support_enabled",
    },
)


def get_user_preferences(*, user: CustomUser) -> UserPreferences:
    """Return the preference record owned by the authenticated user.

    Args:
        user: The authenticated local user obtained from the Django session.

    Returns:
        The user's existing preference record.

    Raises:
        UserPreferences.DoesNotExist: If the preference provisioning invariant
            has been violated.
    """
    return UserPreferences.objects.get(user=user)


@transaction.atomic
def update_user_preferences(
    *,
    user: CustomUser,
    changes: Mapping[str, object],
) -> UserPreferences:
    """Apply validated preference changes and record a minimal audit event.

    Args:
        user: The authenticated local user obtained from the Django session.
        changes: The serializer-validated fields to update.

    Returns:
        The updated user preference record.

    Raises:
        ValueError: If a caller bypasses the serializer with empty or unknown
            preference fields.
        ValidationError: If an allowed preference field contains an invalid
            value.
        UserPreferences.DoesNotExist: If the preference provisioning invariant
            has been violated.
    """
    unknown_fields = set(changes) - UPDATABLE_PREFERENCE_FIELDS

    if not changes:
        raise ValueError("El conjunto de cambios de preferencias no puede estar vacío.")

    if unknown_fields:
        raise ValueError(
            "El conjunto de cambios de preferencias contiene campos no permitidos."
        )

    # Serialize concurrent updates for the authenticated user's existing row.
    preferences = UserPreferences.objects.select_for_update().get(
        user=user,
    )

    effective_changes = {
        field_name: value
        for field_name, value in changes.items()
        if getattr(preferences, field_name) != value
    }

    if not effective_changes:
        return preferences

    for field_name, value in effective_changes.items():
        # Equivalent to x.y = z
        setattr(preferences, field_name, value)

    preferences.full_clean()

    # Save only the modified fields + the update timestamp (updated_at).
    preferences.save(update_fields=(*effective_changes.keys(), "updated_at"))
    SecurityEvent.objects.record(
        event_type=SecurityEventType.PREFERENCES_UPDATED,
        actor=user,
    )
    return preferences
