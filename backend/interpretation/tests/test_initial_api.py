"""Regression tests for the public health endpoint."""

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


class HealthApiTests(SimpleTestCase):
    """Verify health metadata exposes no sensitive or persisted content."""

    client_class = APIClient

    def test_health_endpoint_returns_minimal_non_cacheable_status(self) -> None:
        """Expose only stable liveness fields with cache protection.

        Args:
            self: The test case instance.
        """
        response = self.client.get(reverse("api-health"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "status": "ok",
                "service": "django",
            },
        )
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(response["Pragma"], "no-cache")

    def test_health_endpoint_rejects_post(self) -> None:
        """Reject unsafe methods for the read-only health endpoint."""
        response = self.client.post(reverse("api-health"))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
