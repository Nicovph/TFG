"""URL routes for health and pragmatic interpretation APIs."""

from django.urls import path

from . import views


urlpatterns = [
    path("health/", views.health, name="api-health"),
    path(
        "interpretations/",
        views.InterpretationView.as_view(),
        name="api-interpretation",
    ),
]
