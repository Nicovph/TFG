"""Structured, data-minimised security audit events."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import uuid
from collections.abc import Iterable
from typing import NoReturn

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from .request_context import get_current_request_id


# Validator for the stored keyed HMAC-SHA-256 IP pseudonym. This enforces the expected
# lowercase SHA-256 hexadecimal representation for source IP pseudonyms.
source_hash_validator = RegexValidator(
    regex=r"\A[0-9a-f]{64}\Z",
    message="El hash de origen debe ser un resumen hexadecimal SHA-256 en minúsculas.",
    code="invalid_source_hash",
)


def pseudonymize_ip_address(ip_address: str, *, key: bytes) -> str:
    """Return a keyed, irreversible (without the secret key) identifier for an IPv4 or IPv6 address.
    
    Args:
        ip_address: The IP address to pseudonymize (IPv4 or IPv6).
        key: The secret key for HMAC (must be bytes and kept secret).
    
    Returns:
        A hexadecimal SHA-256 digest that cannot be reversed.
    
    Raises:
        ValueError: If the key is empty or the address is not valid IPv4/IPv6.
    """
    if not key:
        raise ValueError("Se requiere una clave de pseudonimización no vacía.")

    # Normalize the IP address to its binary form before hashing. This makes
    # the pseudonymization consistent across different address string formats.
    normalized_address = ipaddress.ip_address(ip_address) # Creates a valid IP address object
    return hmac.new(
        key,
        normalized_address.packed, # Returns the packed binary representation (in bytes) of the IP address
        hashlib.sha256,
    ).hexdigest() # Converts the binary hash to a hexadecimal string.

# To avoid errors like: SecurityEvent.objects.filter(...).update(...) o
# SecurityEvents.objects.filter(...).delete()
class SecurityEventQuerySet(models.QuerySet):
    """QuerySet that blocks bulk mutation of audit events."""

    def bulk_create(
        self,
        objs: Iterable[models.Model],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> NoReturn:
        """Reject bulk inserts that bypass model validation and save hooks.

        Args:
            objs: Model instances that would be inserted.
            batch_size: Optional maximum number of objects per insert query.
            ignore_conflicts: Whether insertion conflicts would be ignored.
            update_conflicts: Whether conflicts would update existing rows.
            update_fields: Fields that would be updated after a conflict.
            unique_fields: Fields used to identify insertion conflicts.

        Raises:
            ValidationError: Always, because events must use the validated
                recording interface.
        """
        raise ValidationError(
            "Los eventos de seguridad no pueden crearse en bloque; "
            "debe utilizarse la interfaz de registro validada."
        )

    def bulk_update(
        self,
        objs: Iterable[models.Model],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject bulk updates before Django opens its internal transaction.

        Args:
            objs: Model instances that would be updated.
            fields: Model fields that would be written.
            batch_size: Optional maximum number of objects per update query.

        Raises:
            ValidationError: Always, because audit events are immutable.
        """
        raise ValidationError(
            "Los eventos de seguridad no pueden actualizarse en bloque."
        )

    def update(self, **kwargs: object) -> int:
        """Reject bulk updates to preserve append-only audit integrity.

        Args:
            **kwargs: Field names and values that would be updated.

        Raises:
            ValidationError: Always, because audit events cannot be updated in bulk.
        """
        raise ValidationError(
            "Los eventos de seguridad no pueden actualizarse en bloque."
        )

    def delete(self) -> tuple[int, dict[str, int]]:
        """Reject bulk deletion outside the controlled retention process.

        Raises:
            ValidationError: Always, because retention must use an explicit process.
        """
        raise ValidationError(
            "Los eventos de seguridad solo pueden eliminarse "
            "mediante el proceso de retención."
        )


class SecurityEventManager(models.Manager.from_queryset(SecurityEventQuerySet)):
    """Create validated events through a narrow, structured interface."""

    def record(
        self,
        *,
        event_type: str,
        actor: models.Model | None = None,
        source_ip_hash: str = "",
        request_id: uuid.UUID | None = None,
    ) -> SecurityEvent:
        """Create and persist a new security event record.
        
        Args:
            event_type: The event type (must be a valid EventType choice).
            actor: Optional user actor associated with the event.
            source_ip_hash: Optional HMAC-SHA-256 digest of the source IP.
            request_id: Optional explicit request correlation identifier. When
                omitted during an HTTP request, the trusted server-generated
                identifier from the current request context is used.
        
        Returns:
            The newly created and inserted SecurityEvents instance.
        """
        resolved_request_id = (
            request_id
            if request_id is not None
            else get_current_request_id()
        )
        event = self.model(
            event_type=event_type,
            actor=actor,
            source_ip_hash=source_ip_hash,
            request_id=resolved_request_id,
        )
        event.save(force_insert=True)
        return event

# Predefined audit event categories used for filtering and reporting.
class SecurityEventType(models.TextChoices):
    ACCOUNT_CREATED = "account_created", "Cuenta creada"
    ACCOUNT_SECURITY_UPDATED = "account_updated", "Estado de seguridad de la cuenta actualizado"
    LOGIN_SUCCEEDED = "login_succeeded", "Inicio de sesión exitoso"
    LOGIN_FAILED = "login_failed", "Inicio de sesión fallido"
    IDENTITY_REJECTED = "identity_rejected", "Identidad OIDC rechazada"
    LOGOUT = "logout", "Cierre de sesión"
    SESSION_REVOKED = "session_revoked", "Sesión revocada"
    AUTHORIZATION_DENIED = "authorization_denied", "Autorización denegada"
    RATE_LIMITED = "rate_limited", "Solicitud limitada por tasa"
    PREFERENCES_UPDATED = "preferences_updated", "Preferencias actualizadas"
    LLM_REQUEST_REJECTED = "llm_request_rejected", "Solicitud al LLM rechazada"
    LLM_PROVIDER_ERROR = "llm_provider_error", "Error del proveedor LLM"
    ARASAAC_PROVIDER_ERROR = "arasaac_provider_error", "Error de ARASAAC"

class SecurityEvent(models.Model):
    """
    Append-only security event containing no arbitrary free-form content.

    OAuth parameters, tokens, prompts, messages, names, email addresses, raw
    IP addresses, user-agent strings, LLM responses, and exception text must never be stored
    in this model.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    # Event name that indicates the type of audit action performed.
    event_type = models.CharField(
        max_length=32,
        choices=SecurityEventType.choices,
    )
    # Optional actor reference that can be null for unauthenticated events.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_events",
    )
    # Optional snapshot of the actor's UUID at the time of the event, for traceability if the account is deleted.
    actor_id_snapshot = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        help_text="Copia del UUID local del actor para conservar trazabilidad si la cuenta se elimina.",
    )
    # Hashed source IP address; raw IPs must never be persisted here.
    source_ip_hash = models.CharField(
        max_length=64,
        blank=True,
        validators=[source_hash_validator],
        help_text="Resumen HMAC-SHA-256 de la IP de origen; "
                  "nunca una dirección IP sin procesar.",
    )
    # Optional request correlation identifier for later tracing.
    request_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Identificador de correlación opcional generado por la aplicación.",
    )
    # Timestamp when the audit event was created.
    occurred_at = models.DateTimeField(
        auto_now_add=True,
    )

    objects = SecurityEventManager()

    class Meta:
        verbose_name = "evento de seguridad"
        verbose_name_plural = "eventos de seguridad"
        ordering = ("-occurred_at",)
        default_permissions = ("view",)
        indexes = [
            models.Index(
                fields=("event_type", "-occurred_at"),
                name="audit_event_type_time_idx",
            ),
            models.Index(
                fields=("actor", "-occurred_at"),
                name="audit_actor_time_idx",
            ),
            # Partial index on actor_id_snapshot for efficient lookups when
            # the snapshot is present. Using a partial index reduces storage
            # and write overhead compared with indexing all rows.
            models.Index(
                fields=("actor_id_snapshot", "-occurred_at"),
                name="audit_actor_snapshot_time_idx",
                condition=models.Q(actor_id_snapshot__isnull=False),
            ),
            models.Index(
                fields=("request_id",),
                name="audit_request_id_idx",
                condition=models.Q(request_id__isnull=False),
            ),
        ]
        constraints = [ # Protects against direct insertions or errors that do not pass through normal validation.
            models.CheckConstraint(
                condition=models.Q(event_type__in=SecurityEventType.values),
                name="audit_event_type_valid",
            ),
        ]

    def clean(self) -> None:
        """Validate audit attribution without storing sensitive content.

        Raises:
            ValidationError: If the event lacks actor, source IP hash and request ID.
        """
        super().clean()

        has_actor = self.actor_id is not None
        has_source = bool(self.source_ip_hash)
        has_request = self.request_id is not None

        if not (has_actor or has_source or has_request):
            raise ValidationError(
                "El evento de seguridad debe incluir al menos actor, "
                "source_ip_hash o request_id."
            )        

    def save(self, *args: object, **kwargs: object) -> None:
        """Validate inserts and reject updates to preserve audit integrity.
        
        Args:
            *args: Positional arguments passed to the parent save method.
            **kwargs: Keyword arguments passed to the parent save method.
        
        Raises:
            ValidationError: If attempting to update an existing event.
        """
        if not self._state.adding: # If someone tries to update an existing event, this will be rejected. 
            # Only new events can be added; existing events are immutable.
            raise ValidationError("Los eventos de seguridad son de solo adición.")
        
        if self.actor and self.actor_id_snapshot is None:
            # Capture the actor's UUID at the time of the event for traceability.
            self.actor_id_snapshot = self.actor.id

        self.full_clean()
        super().save(*args, **kwargs)

    def delete(
        self,
        *args: object,
        **kwargs: object,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion outside an explicit retention process.
        
        Args:
            *args: Positional arguments (unused, deletion is always rejected).
            **kwargs: Keyword arguments (unused, deletion is always rejected).
        
        Raises:
            ValidationError: Always, since security events are only deleted
                through the explicit retention process.
        """
        raise ValidationError(
            "Los eventos de seguridad solo pueden ser eliminados por el proceso de retención."
        )

    def __str__(self) -> str:
        """Return a CRLF-free string representation to prevent log injection attacks.

        By restricting the output to a single-line format without carriage returns
        or line feeds, this method prevents malicious actors from embedding newline
        characters to inject false audit entries into log streams. This preserves
        audit trail integrity and parser safety for log aggregation tools.
        
        Returns:
            A string formatted as 'event_type:id' with no embedded newlines.
        """
        safe_event_type = (
            self.event_type
            if self.event_type in SecurityEventType.values
            else "invalid_event_type"
        )
        return f"{safe_event_type}:{self.id}"
