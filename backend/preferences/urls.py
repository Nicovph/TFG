"""URL routes for authenticated user preference operations."""

from django.urls import path

from . import views


urlpatterns = [
    path("preferences/", views.user_preferences, name="user-preferences"),
]
