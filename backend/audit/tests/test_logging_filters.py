"""Tests for security filters applied before Django request log handlers."""

import logging

from django.test import SimpleTestCase

from ..logging_filters import DjangoServerQueryStringFilter


class DjangoServerQueryStringFilterTests(SimpleTestCase):
    """Verify request metadata remains useful without retaining query data."""

    def test_filter_removes_query_and_preserves_request_metadata(self) -> None:
        """Keep method, path and status while removing every query value.

        Args:
            self: The test case instance.
        """
        authorization_code = "sensitive-authorization-code"
        state = "sensitive-state"
        id_token = "sensitive-id-token"
        record = logging.LogRecord(
            name="django.server",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='"%s" %s %s',
            args=(
                "GET /api/auth/google/callback/"
                f"?code={authorization_code}&state={state}&id_token={id_token} "
                "HTTP/1.1",
                "302",
                "0",
            ),
            exc_info=None,
        )

        accepted = DjangoServerQueryStringFilter().filter(record)
        rendered = record.getMessage()

        self.assertTrue(accepted)
        self.assertEqual(
            rendered,
            '"GET /api/auth/google/callback/ HTTP/1.1" 302 0',
        )
        for sensitive_value in (authorization_code, state, id_token):
            with self.subTest(sensitive_value=sensitive_value):
                self.assertNotIn(sensitive_value, rendered)

    def test_project_logger_filters_before_attached_handler(self) -> None:
        """Ensure the configured django.server logger protects new handlers.

        Args:
            self: The test case instance.
        """
        sensitive_query = "code=secret-code&state=secret-state"

        with self.assertLogs("django.server", level="INFO") as captured:
            logging.getLogger("django.server").info(
                '"%s" %s %s',
                "GET /api/auth/google/callback/"
                f"?{sensitive_query} HTTP/1.1",
                "302",
                "0",
            )

        rendered = " ".join(captured.output)
        self.assertIn("GET /api/auth/google/callback/ HTTP/1.1", rendered)
        self.assertIn("302", rendered)
        self.assertNotIn("secret-code", rendered)
        self.assertNotIn("secret-state", rendered)
