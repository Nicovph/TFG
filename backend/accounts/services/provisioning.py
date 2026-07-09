"""Local account provisioning and promotion for federated users."""

from dataclasses import dataclass
from typing import Mapping

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from backend.audit.models import SecurityEvent, SecurityEventType
from backend.preferences.models import UserPreferences

from ..models import CustomUser, google_subject_validator
from .exceptions import GoogleOIDCTokenError


@dataclass(frozen=True)
class GoogleLoginResult:
    """Result of a completed Google login flow.

    Args:
        user: The local user authenticated in the Django session.
        created: Whether the local user was provisioned during this login.
    """

    user: CustomUser
    created: bool


def provision_user_from_claims(claims: Mapping[str, object]) -> GoogleLoginResult:
    """Create or retrieve the minimal local account for validated OIDC claims.

    Args:
        claims: The validated ID token claims.

    Returns:
        A GoogleLoginResult with the local user and whether it was created.

    Raises:
        GoogleOIDCTokenError: If the subject claim is absent or invalid.
    """
    subject = claims.get("sub")

    if not isinstance(subject, str) or not subject:
        raise GoogleOIDCTokenError("Claim OIDC obligatorio ausente: sub.")

    try:
        google_subject_validator(subject)
    except ValidationError as exc:
        raise GoogleOIDCTokenError("Subject OIDC no válido.") from exc

    # If an exception occurs, the process is reversed.
    with transaction.atomic():
        try:
            user = CustomUser.objects.get(google_subject=subject)
            created = False
        except CustomUser.DoesNotExist:
            try:
                user = CustomUser.objects.create_user(google_subject=subject)
                created = True
            except IntegrityError:
                user = CustomUser.objects.get(google_subject=subject)
                created = False

        if created:
            UserPreferences.objects.get_or_create(user=user)
            SecurityEvent.objects.record(
                event_type=SecurityEventType.ACCOUNT_CREATED,
                actor=user,
            )

    return GoogleLoginResult(user=user, created=created)


def promote_user(user: CustomUser) -> CustomUser:
    """Promote an existing federated user to Django admin superuser status.

    Args:
        user: The existing local federated user to promote.

    Returns:
        The promoted user instance.

    Raises:
        ValidationError: If the user cannot be saved with the promoted state.
    """
    user.is_active = True
    user.is_staff = True
    user.is_superuser = True
    user.set_unusable_password()
    user.full_clean()
    user.save()
    SecurityEvent.objects.record(
        event_type=SecurityEventType.ACCOUNT_SECURITY_UPDATED,
        actor=user,
    )
    return user
