"""Public health and protected pragmatic interpretation API views."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from django.http.response import HttpResponseBase
from django.utils.cache import patch_cache_control
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAcceptable,
    NotAuthenticated,
    ParseError,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
    ValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.models import CustomUser
from backend.audit.models import SecurityEventType
from backend.audit.services import record_security_event_best_effort

from .rate_limit_audit import record_llm_rate_limit_best_effort
from .provider import (
    LlmProviderBusyError,
    LlmProviderConfigurationError,
    LlmProviderError,
    LlmProviderResponseError,
    LlmProviderTransientError,
)
from .rate_limits import (
    LlmQuotaReservationTooLarge,
    LlmRateLimitExceeded,
)
from .serializers import InterpretationRequestSerializer
from .services import (
    DuplicateInterpretationRequest,
    InterpretationConfigurationError,
    InterpretationOutputRejected,
    OffensiveLanguageOutputRejected,
    interpret_message,
)
from .throttles import (
    InterpretationBurstThrottle,
    InterpretationSustainedThrottle,
)


def _apply_no_store_headers(response: HttpResponseBase) -> HttpResponseBase:
    """Apply privacy-preserving cache directives to one HTTP response.

    Args:
        response: Final response produced by Django REST Framework.

    Returns:
        The same response with browser and shared-cache storage disabled.
    """
    # private excludes shared caches, while Pragma supports older HTTP/1.0
    # intermediaries that may not understand the Cache-Control directive.
    patch_cache_control(response, no_store=True, private=True)
    response["Pragma"] = "no-cache"
    return response


def _no_store_response(
    data: object,
    *,
    response_status: int = status.HTTP_200_OK,
) -> Response:
    """Create a JSON response that browsers and proxies must not cache.

    Args:
        data: Already minimized response payload.
        response_status: HTTP status code for the response.

    Returns:
        A DRF response with strict no-store cache directives.
    """
    response = Response(data, status=response_status)
    _apply_no_store_headers(response)
    return response


def _error_response(
    *,
    error: str,
    message: str,
    response_status: int,
    fields: object | None = None,
) -> Response:
    """Build one stable content-free API error representation.

    Args:
        error: Closed machine-readable error code.
        message: Spanish human-readable message without internal detail.
        response_status: HTTP status code for the response.
        fields: Optional normalized serializer validation details.

    Returns:
        A DRF error response using one consistent envelope.
    """
    payload: dict[str, object] = {
        "error": error,
        "message": message,
    }

    if fields is not None:
        payload["fields"] = fields

    return Response(payload, status=response_status)


def _json_safe_validation_details(value: object) -> object:
    """Convert DRF validation details into JSON-native closed structures.

    Args:
        value: Nested result returned by ValidationError.get_full_details().

    Returns:
        Dictionaries, lists, and strings safe for the JSON renderer.
    """
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_validation_details(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_details(item) for item in value]

    return str(value)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Return minimal liveness metadata without checking external providers.

    Args:
        request: HTTP request received by Django REST Framework.

    Returns:
        A non-sensitive health response.
    """
    return _no_store_response(
        {
            "status": "ok",
            "service": "django",
        }
    )


class NoStoreAPIView(APIView):
    """Apply no-store headers to every DRF-managed response path."""

    def finalize_response(
        self,
        request: Request,
        response: HttpResponseBase,
        *args: object,
        **kwargs: object,
    ) -> HttpResponseBase:
        """Finalize content negotiation and enforce response cache policy.

        This hook also covers authentication, permission, parser, media-type,
        method, throttle, validation, and domain exceptions converted into a
        response by DRF. An unhandled exception re-raised as a server error does
        not pass through this hook and is intentionally not claimed here.

        Args:
            request: DRF request associated with the response.
            response: Response returned or produced by exception handling.
            *args: Positional dispatch context passed by DRF.
            **kwargs: Keyword dispatch context passed by DRF.

        Returns:
            The finalized response with no-store cache directives.
        """
        finalized = super().finalize_response(
            request,
            response,
            *args,
            **kwargs,
        )
        return _apply_no_store_headers(finalized)


class InterpretationView(NoStoreAPIView):
    """Interpret transient text for the authenticated session user."""

    permission_classes = [IsAuthenticated]
    # These inexpensive controls run after authentication but before request.data
    # is parsed. PostgreSQL quotas remain authoritative for provider consumption.
    throttle_classes = [
        InterpretationBurstThrottle,
        InterpretationSustainedThrottle,
    ]

    def post(self, request: Request) -> Response:
        """Validate, minimize, interpret, and return one transient result.

        Args:
            request: Authenticated JSON request with target, optional context,
                and external-processing acknowledgment.

        Returns:
            A validated interpretation using only the closed output contract.

        Raises:
            ValidationError: If the request fails the closed serializer policy.
            DuplicateInterpretationRequest: If an identical request is recent.
            LlmProviderError: If the external provider cannot return valid output.
            LlmRateLimitExceeded: If an application-owned quota is exhausted.
        """
        # IsAuthenticated and AUTH_USER_MODEL guarantee this type before post().
        # cast() informs static analysis without adding a redundant runtime branch.
        user = cast(CustomUser, request.user)
        serializer = InterpretationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = interpret_message(
            user=user,
            target_message=serializer.validated_data["target_message"],
            previous_context=serializer.validated_data["previous_context"],
            previous_context_speaker=serializer.validated_data[
                "previous_context_speaker"
            ],
            following_context=serializer.validated_data["following_context"],
            following_context_speaker=serializer.validated_data[
                "following_context_speaker"
            ],
        )

        # Emit only JSON-native values from the already validated Pydantic model.
        response_payload = result.output.model_dump(mode="json")
        response_payload["show_content_warning"] = result.show_content_warning
        return Response(response_payload)

    def handle_exception(self, exc: Exception) -> Response:
        """Map handled failures to stable Spanish, content-free API errors.

        Args:
            exc: Exception raised during DRF initialization or interpretation.

        Returns:
            A minimized response for known failures.

        Raises:
            Exception: Re-raises unknown failures through DRF's default handler.
        """
        # Only ValidationError carries per-field details worth exposing; all other
        # handled failures remain minimal and content-free.
        if isinstance(exc, ValidationError):
            return _error_response(
                error="invalid_interpretation_request",
                message="La solicitud de interpretación no es válida.",
                response_status=status.HTTP_400_BAD_REQUEST,
                fields=_json_safe_validation_details(exc.get_full_details()),
            )

        if isinstance(exc, ParseError):
            return _error_response(
                error="invalid_json",
                message=(
                    "El cuerpo de la solicitud debe contener un objeto JSON "
                    "válido."
                ),
                response_status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(exc, UnsupportedMediaType):
            return _error_response(
                error="unsupported_media_type",
                message="El contenido debe enviarse como JSON.",
                response_status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            return _error_response(
                error="authentication_required",
                message=(
                    "Debes iniciar sesión para solicitar una interpretación."
                ),
                response_status=status.HTTP_403_FORBIDDEN,
            )

        # Authenticated POST request without a valid CSRF token.
        if isinstance(exc, PermissionDenied):
            return _error_response(
                error="permission_denied",
                message="No tienes permiso para realizar esta solicitud.",
                response_status=status.HTTP_403_FORBIDDEN,
            )

        if isinstance(exc, MethodNotAllowed):
            return _error_response(
                error="method_not_allowed",
                message="El método HTTP no está permitido para este recurso.",
                response_status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )

        if isinstance(exc, NotAcceptable):
            return _error_response(
                error="not_acceptable",
                message="La respuesta solo está disponible en formato JSON.",
                response_status=status.HTTP_406_NOT_ACCEPTABLE,
            )

        if isinstance(exc, Throttled):
            retry_after = max(1, math.ceil(exc.wait or 1))
            response = _error_response(
                error="interpretation_attempt_rate_limited",
                message=(
                    "Has realizado demasiados intentos de interpretación. "
                    "Inténtalo de nuevo más tarde."
                ),
                response_status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(retry_after)
            return response

        if isinstance(exc, DuplicateInterpretationRequest):
            return _error_response(
                error="duplicate_interpretation_request",
                message=(
                    "Se ha enviado recientemente una solicitud de "
                    "interpretación idéntica."
                ),
                response_status=status.HTTP_409_CONFLICT,
            )

        if isinstance(exc, LlmRateLimitExceeded):
            user = cast(CustomUser, self.request.user)
            record_llm_rate_limit_best_effort(
                actor=user,
                retry_after_seconds=exc.retry_after_seconds,
            )
            response = _error_response(
                error="interpretation_rate_limited",
                message=(
                    "Se ha alcanzado temporalmente el límite de solicitudes "
                    "de interpretación."
                ),
                response_status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = str(exc.retry_after_seconds)
            return response

        if isinstance(exc, LlmProviderResponseError):
            return _error_response(
                error="invalid_provider_response",
                message=(
                    "El proveedor no devolvió una interpretación válida."
                ),
                response_status=status.HTTP_502_BAD_GATEWAY,
            )

        if isinstance(exc, InterpretationOutputRejected):
            user = cast(CustomUser, self.request.user)
            record_security_event_best_effort(
                event_type=SecurityEventType.LLM_OUTPUT_REJECTED,
                actor=user,
            )
            if isinstance(exc, OffensiveLanguageOutputRejected):
                return _error_response(
                    error="offensive_language_hidden",
                    message=(
                        "La respuesta generada incluía lenguaje ofensivo y tu "
                        "preferencia está configurada para ocultarlo. No se ha "
                        "mostrado ese contenido. Puedes intentarlo de nuevo."
                    ),
                    response_status=status.HTTP_502_BAD_GATEWAY,
                )
            return _error_response(
                error="invalid_interpretation_response",
                message=(
                    "La interpretación generada no superó las reglas de "
                    "seguridad."
                ),
                response_status=status.HTTP_502_BAD_GATEWAY,
            )

        if isinstance(exc, (LlmProviderTransientError, LlmProviderBusyError)):
            return _error_response(
                error="interpretation_temporarily_unavailable",
                message=(
                    "La interpretación no está disponible temporalmente. "
                    "Inténtalo de nuevo más tarde."
                ),
                response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if isinstance(
            exc,
            (
                LlmProviderConfigurationError,
                LlmQuotaReservationTooLarge,
                InterpretationConfigurationError,
            ),
        ):
            return _error_response(
                error="interpretation_not_configured",
                message=(
                    "El servicio de interpretación no está configurado "
                    "correctamente."
                ),
                response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if isinstance(exc, LlmProviderError):
            return _error_response(
                error="interpretation_provider_error",
                message="No se pudo completar la interpretación.",
                response_status=status.HTTP_502_BAD_GATEWAY,
            )

        return super().handle_exception(exc)
