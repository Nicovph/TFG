"""Tests for the initial API endpoints used during the second iteration."""

import json

from django.test import SimpleTestCase # Because it is not necessary to access the database.
from django.urls import reverse # To resolve URL names to paths to avoid hardcoding them in tests.
from rest_framework import status # Constains constants for HTTP status codes (e.g., status.HTTP_200_OK, status.HTTP_404_NOT_FOUND).
from rest_framework.test import APIClient # To simulate HTTP requests to the API endpoints and check their responses.


class InitialApiTests(SimpleTestCase):
    """Verify simple API endpoints expose no sensitive or persisted content."""

    client_class = APIClient

    def test_health_endpoint_returns_minimal_metadata(self) -> None:
        """Check the React-Django connectivity endpoint response.

        Args:
            self: The test case instance.
        """
        response = self.client.get(reverse("api-health"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        payload = response.data
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "django")
        self.assertNotIn("POSTGRES_PASSWORD", json.dumps(payload)) # json.dumps serializes Python objects to a string with JSON format.

    def test_health_endpoint_rejects_post(self) -> None:
        """Reject unsafe methods for a read-only health endpoint.

        Args:
            self: The test case instance.
        """
        response = self.client.post(reverse("api-health"))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_mock_interpretation_endpoint_returns_fixed_payload(self) -> None:
        """Return a deterministic mock response without accepting user text.

        Args:
            self: The test case instance.
        """
        response = self.client.get(reverse("api-mock-interpretation"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        payload = response.data
        self.assertEqual(payload["kind"], "mock_interpretation")
        self.assertEqual(payload["tone"], "neutral")
        self.assertIsInstance(payload["visual_concepts"], list)

    def test_mock_interpretation_endpoint_rejects_posted_messages(self) -> None:
        """Avoid receiving user messages in the second iteration mock endpoint.

        Args:
            self: The test case instance.
        """
        response = self.client.post(
            reverse("api-mock-interpretation"),
            data={"message": "texto sensible"},
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)