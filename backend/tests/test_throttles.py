"""Tests for shared pseudonymous throttle configuration."""

from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from rest_framework.request import Request
from rest_framework.views import APIView

from backend.throttles import PseudonymousRateThrottle


class _ConfiguredThrottle(PseudonymousRateThrottle):
    """Provide a complete synthetic throttle for configuration tests."""

    key_salt = "test.configured"
    scope = "test_configured"
    rate_setting = "TEST_THROTTLE_RATE"
    rate_period = "minute"

    def get_subject(self, request: Request, view: APIView) -> str:
        """Return a fixed non-sensitive test subject.

        Args:
            request: Synthetic DRF request.
            view: Synthetic DRF view.

        Returns:
            A fixed non-sensitive subject.
        """
        return "synthetic-subject"


class SharedThrottleConfigurationTests(SimpleTestCase):
    """Verify incomplete throttle subclasses fail before serving requests."""

    def test_subject_method_must_be_implemented(self) -> None:
        """Reject a concrete throttle without a subject-selection policy.

        Args:
            self: The test case instance.
        """
        class MissingSubjectThrottle(PseudonymousRateThrottle):
            """Deliberately omit the abstract subject-selection method."""

            key_salt = "test.missing-subject"
            scope = "test_missing_subject"
            rate_setting = "TEST_THROTTLE_RATE"
            rate_period = "minute"

        with self.assertRaises(TypeError):
            MissingSubjectThrottle()

    @override_settings(TEST_THROTTLE_RATE=1)
    def test_class_configuration_must_be_valid(self) -> None:
        """Reject missing, empty and unsupported class configuration.

        Args:
            self: The test case instance.
        """
        invalid_values = {
            "key_salt": "",
            "scope": None,
            "rate_setting": "   ",
            "rate_period": "month",
        }

        for attribute, value in invalid_values.items():
            with self.subTest(attribute=attribute), mock.patch.object(
                _ConfiguredThrottle,
                attribute,
                value,
            ):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    attribute,
                ):
                    _ConfiguredThrottle()

    def test_rate_setting_must_exist_and_be_a_positive_integer(self) -> None:
        """Reject an absent, non-integer or non-positive Django setting.

        Args:
            self: The test case instance.
        """
        with self.assertRaisesRegex(ImproperlyConfigured, "requerida"):
            _ConfiguredThrottle()

        for value in (None, True, "1", 0, -1):
            with self.subTest(value=value), self.settings(TEST_THROTTLE_RATE=value):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "entero positivo",
                ):
                    _ConfiguredThrottle()

        with self.settings(TEST_THROTTLE_RATE=2):
            throttle = _ConfiguredThrottle()

        self.assertEqual(throttle.rate, "2/minute")
