"""User model for identities authenticated by Google OpenID Connect.

This module defines a minimal local account record that is linked to an
OIDC subject and intentionally does not store usable local password credentials or
profile claim data such as email and name.
"""

from __future__ import annotations # Postpone evaluation of type annotations.
# It permits reference to CustomUser in CustomUserManager, before its definition.

import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


# Validate the expected format of the Google OIDC subject without
# normalizing or modifying its value (without whitespace or non-printable characters).
google_subject_validator = RegexValidator(
    regex=r"\A[\x21-\x7e]{1,255}\Z",
    message=(
        "El subject de Google debe contener entre 1 y 255 "
        "caracteres ASCII imprimibles."
    ),
    code="invalid_google_subject",
)


class CustomUserManager(BaseUserManager):
    """Create local users that can authenticate only through Google OIDC."""

    use_in_migrations = True # Allow this manager to be referenced by historical migration models.

    def _create_user(
        self,
        google_subject: str,
        password: str | None = None, # Initial value of the password is set to None.
        **extra_fields: object,
    ) -> CustomUser: # This function is used, because normal users and superusers share this
        # core behavior. Is a protected method (for internal use only).
        """Internal helper that creates users while forbidding local passwords.
        
        Args:
            google_subject: The OIDC subject identifier from the identity provider.
            password: Must be None or empty string; local passwords are not supported.
            **extra_fields: Additional fields to set on the user instance.
        
        Returns:
            The newly created CustomUser instance.
        
        Raises:
            ValueError: If google_subject is empty or password is non-empty.
            ValidationError: If field constraints or unique constraints are violated.
        """
        if not google_subject:
            raise ValueError("Debe proporcionarse el subject de Google.")

        if password not in (None, ""):
            raise ValueError("No se admiten contraseñas locales.")

        user = self.model(
            google_subject=google_subject,
            **extra_fields,
        )
        user.set_unusable_password()
        user.full_clean() # Validates individual field constraints, model-level constraints and unique constraints. 
        # Raises ValidationError if any validation fails.
        user.save(using=self._db) # Save the user instance in the database db (project's database).
        return user

    def create_user(
        self,
        google_subject: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> CustomUser:
        """Create an unprivileged federated user record.
        
        Args:
            google_subject: The OIDC subject identifier from the identity provider.
            password: Must be None or empty string.
            **extra_fields: Additional fields to set on the user instance.
        
        Returns:
            A new CustomUser with is_staff=False and is_superuser=False.
        """
        extra_fields["is_staff"] = False
        extra_fields["is_superuser"] = False
        return self._create_user(
            google_subject,
            password=password,
            **extra_fields,
        )

    def create_staff_user(
        self,
        google_subject: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> CustomUser:
        """Create a non-superuser staff account for administrative workflows.

        Args:
            google_subject: The OIDC subject identifier from the identity provider.
            password: Must be None or empty string.
            **extra_fields: Additional fields to set on the user instance.

        Returns:
            A new CustomUser with is_staff=True and is_superuser=False.
        """
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = False
        return self._create_user(
            google_subject,
            password=password,
            **extra_fields,
        )

    def create_superuser(
        self,
        google_subject: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> CustomUser:
        """Create a federated administrator without a local password.
        
        Args:
            google_subject: The OIDC subject identifier from the identity provider.
            password: Must be None or empty string.
            **extra_fields: Additional fields to set on the user instance.
        
        Returns:
            A new CustomUser with is_staff=True, is_superuser=True, and is_active=True.
        
        Raises:
            ValueError: If is_staff, is_superuser, or is_active cannot be set to True.
        """
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superusuario debe tener is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superusuario debe tener is_superuser=True.")
        
        if extra_fields.get("is_active") is not True:
            raise ValueError("Un superusuario debe tener is_active=True.") # Avoids creating a superuser that cannot log in.

        return self._create_user(
            google_subject,
            password=password,
            **extra_fields,
        )


class CustomUser(AbstractUser):
    """
    Minimal local account linked to a validated Google OIDC identity.

    Profile claims such as name and email are deliberately not persisted.
    The OIDC integration must match accounts exclusively by ``sub`` after
    validating the token issuer, audience, signature, expiry, and nonce.
    """

    # Use a non-sequential UUID as the internal primary key.
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # These AbstractUser fields are unnecessary for a Google-only identity.
    username = None
    first_name = None
    last_name = None
    email = None

    # The OIDC subject received from the identity provider. Hidden from automatic model 
    # forms and treated as immutable by the application service layer.
    google_subject = models.CharField(
        max_length=255,
        unique=True,
        editable=False,
        validators=[google_subject_validator],
        verbose_name="Subject de Google", # Legible name for forms and admin interfaces.
        help_text="Valor opaco del claim sub del ID token de Google validado.",
    )
    # Track when the user record was last updated.
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="fecha de actualización",
    )

    objects = CustomUserManager()

    USERNAME_FIELD = "google_subject"
    REQUIRED_FIELDS: list[str] = []

    class Meta(AbstractUser.Meta):
        """Expose Spanish model names in administration interfaces."""

        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def clean(self) -> None:
        """Preserve the subject exactly as issued.
        
        AbstractUser.clean() normalizes username and email fields. Neither
        operation is valid here because an OIDC subject is an opaque,
        case-sensitive identifier and this model does not store email.
        """
        return None

    def set_password(self, raw_password: str | None) -> None:
        """Prevent accidental activation of Django password authentication.
        
        Args:
            raw_password: Must be None or empty string.
        
        Raises:
            ValueError: If raw_password is non-empty.
        """
        if raw_password not in (None, ""):
            raise ValueError("No se admiten contraseñas locales.")

        self.set_unusable_password()

    def check_password(self, raw_password: str | None) -> bool:
        """Disable local password authentication unconditionally.
        
        Args:
            raw_password: Ignored; always returns False.
        
        Returns:
            Always False.
        """
        return False

    async def acheck_password(self, raw_password: str | None) -> bool:
        """Asynchronous counterpart of check_password.
        
        Args:
            raw_password: Ignored; always returns False.
        
        Returns:
            Always False.
        """
        return False

    def save(self, *args: object, **kwargs: object) -> None:
        """Enforce the no-local-password invariant on every model save.
        
        Args:
            *args: Positional arguments passed to the parent save method.
            **kwargs: Keyword arguments passed to the parent save method.
        
        Raises:
            ValidationError: If a usable password is detected on the instance.
        """
        if not self.password:
            self.set_unusable_password()
        elif self.has_usable_password():
            raise ValidationError(
                {"password": "No se admiten contraseñas locales."}
            )

        super().save(*args, **kwargs) # Delegates to the parent class's save method to handle the actual saving of the model instance to the database.

    def get_full_name(self) -> str:
        """Return no persisted profile name.
        
        Returns:
            Always an empty string.
        """
        return ""

    def get_short_name(self) -> str:
        """Return no persisted profile name.
        
        Returns:
            Always an empty string.
        """
        return ""

    def __str__(self) -> str:
        """Use the non-provider local identifier in logs and admin views.
        
        Returns:
            The UUID primary key as a string.
        """
        return str(self.pk)
