"""Shared primitives for privacy-minimised cache-backed API throttles."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import salted_hmac
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView


class PseudonymousRateThrottle(SimpleRateThrottle, ABC):
    """Build configurable throttle keys without storing raw subject values."""

    key_salt: ClassVar[str]
    rate_period: ClassVar[str]
    rate_setting: ClassVar[str]
    scope: ClassVar[str]
    cache_format = "api-throttle-v1:%(scope)s:%(ident)s"

    def __init__(self) -> None:
        """Validate the concrete throttle before DRF parses its rate.

        Raises:
            ImproperlyConfigured: If a required class setting is missing,
                empty or uses an unsupported period.
        """
        for attribute in ("key_salt", "scope", "rate_setting", "rate_period"):
            value = getattr(self, attribute, None)
            if not isinstance(value, str) or not value.strip():
                raise ImproperlyConfigured(
                    f"{self.__class__.__name__}.{attribute} debe ser una cadena de texto no vacía."
                )

        if self.rate_period not in {"second", "minute", "hour", "day"}:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__}.rate_period no es compatible."
            )

        super().__init__()

    def get_rate(self) -> str:
        """Build the DRF rate from validated server configuration.

        Raises:
            ImproperlyConfigured: If the referenced setting is missing or is
                not a positive integer.

        Returns:
            A rate in DRF's number/period format.
        """
        try:
            attempts = getattr(settings, self.rate_setting)
        except AttributeError as exc:
            raise ImproperlyConfigured(
                f"La configuración de Django {self.rate_setting} es requerida."
            ) from exc

        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts <= 0
        ):
            raise ImproperlyConfigured(
                f"La configuración de Django {self.rate_setting} debe ser un entero positivo."
            )

        return f"{attempts}/{self.rate_period}"

    @abstractmethod
    def get_subject(self, request: Request, view: APIView) -> str | None:
        """Return the endpoint-specific subject that owns the rate budget.

        Args:
            request: Request being checked before the view runs.
            view: DRF view protected by this throttle.

        Returns:
            The trusted subject to pseudonymize, or None when the request is
            outside the concrete throttle's policy.
        """

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        """Create a namespaced HMAC cache key for one trusted subject.

        Args:
            request: Request being checked before the view runs.
            view: DRF view protected by this throttle.

        Returns:
            A pseudonymous cache key, or None when the request is not counted.
        """
        subject = self.get_subject(request, view)

        if subject is None:
            return None

        digest = salted_hmac(
            self.key_salt,
            subject,
            secret=settings.SECRET_KEY,
            algorithm="sha256",
        ).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
