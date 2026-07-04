"""Initial API views for the second development iteration."""

from rest_framework.decorators import api_view, permission_classes # api_view: decorator to define function-based views,
                                                                   # permission_classes: decorator to set permissions for the view.
from rest_framework.permissions import AllowAny # Permits access to the view without authentication.
from rest_framework.request import Request
from rest_framework.response import Response
from django.utils.cache import patch_cache_control

from .serializers import ApiHealthSerializer, MockInterpretationSerializer


MOCK_INTERPRETATION = {
    "kind": "mock_interpretation",
    "summary": (
        "La frase se interpreta como un mensaje neutral. Puede necesitar "
        "contexto adicional si hay ironía o intención indirecta."
    ),
    "tone": "neutral",
    "signals": [
        "No se detecta una alerta clara en esta respuesta simulada.",
        "La interpretación real se conectará en una iteración posterior.",
    ],
    "visual_concepts": [
        "comunicar",
        "comprender",
        "contexto",
    ],
}


@api_view(["GET"]) # This view only accepst GET requests. Other methods will return a 405 Method Not Allowed response.
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """Return a minimal API health response for React-Django connectivity checks.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A DRF response with stable, non-sensitive service metadata.
    """
    serializer = ApiHealthSerializer(
        data={
            "status": "ok",
            "service": "django",
            "api_version": "phase-2",
            "features": [
                "health",
                "mock_interpretation",
            ],
        }
    )
    serializer.is_valid(raise_exception=True) # Validates the data against the serializer's schema and raises 
                                              # an exception 400 HTTP Bad Request if invalid.

    response = Response(serializer.data) # Use content negotiation to return the response in the format requested by the client (e.g., JSON).
    patch_cache_control(response, no_store=True) # Adds a Cache-Control: no-store HTTP header to the response to prevent caching of the health check response.
    return response


@api_view(["GET"])
@permission_classes([AllowAny])
def mock_interpretation(request: Request) -> Response:
    """Return a fixed interpretation sample without receiving user text.

    Args:
        request: The HTTP request received by Django REST Framework.

    Returns:
        A DRF response with a deterministic simulated interpretation payload.
    """
    serializer = MockInterpretationSerializer(data=MOCK_INTERPRETATION)
    serializer.is_valid(raise_exception=True)

    response = Response(serializer.data)
    patch_cache_control(response, no_store=True)
    return response