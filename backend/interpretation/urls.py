"""URL routes for the initial interpretation API surface."""

from django.urls import path

from . import views


urlpatterns = [
    path("health/", views.health, name="api-health"),
    path(
        "interpretations/mock/",
        views.mock_interpretation,
        name="api-mock-interpretation",
    ),
]
