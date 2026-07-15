"""Tests for secure Google OIDC secret loading in project settings."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from Traductor_TEA import settings as project_settings


class SecretSettingTests(SimpleTestCase):
    """Validate direct and file-backed secret configuration behavior."""

    def test_returns_direct_secret_when_no_file_is_configured(self) -> None:
        """Return the direct local-development secret after trimming it.

        Args:
            self: The test case instance.
        """
        with mock.patch.object(
            project_settings,
            "aplication_config",
            {"GOOGLE_OIDC_CLIENT_SECRET": "  direct-secret  "},
        ):
            value = project_settings.get_secret_setting(
                "GOOGLE_OIDC_CLIENT_SECRET",
                "GOOGLE_OIDC_CLIENT_SECRET_FILE",
            )

        self.assertEqual(value, "direct-secret")

    def test_reads_secret_from_absolute_file(self) -> None:
        """Read a single-line UTF-8 secret from an absolute file path.

        Args:
            self: The test case instance.
        """
        with TemporaryDirectory() as temporary_directory:
            secret_path = Path(temporary_directory) / "google-secret.txt"
            secret_path.write_text("file-secret\n", encoding="utf-8")

            with mock.patch.object(
                project_settings,
                "aplication_config",
                {"GOOGLE_OIDC_CLIENT_SECRET_FILE": str(secret_path)},
            ):
                value = project_settings.get_secret_setting(
                    "GOOGLE_OIDC_CLIENT_SECRET",
                    "GOOGLE_OIDC_CLIENT_SECRET_FILE",
                )

        self.assertEqual(value, "file-secret")

    def test_rejects_invalid_direct_secret(self) -> None:
        """Reject a direct secret containing control characters.

        Args:
            self: The test case instance.
        """
        with mock.patch.object(
            project_settings,
            "aplication_config",
            {"GOOGLE_OIDC_CLIENT_SECRET": "first-line\nsecond-line"},
        ):
            with self.assertRaises(ImproperlyConfigured):
                project_settings.get_secret_setting(
                    "GOOGLE_OIDC_CLIENT_SECRET",
                    "GOOGLE_OIDC_CLIENT_SECRET_FILE",
                )

    def test_rejects_ambiguous_direct_and_file_sources(self) -> None:
        """Reject configuration that supplies the same secret twice.

        Args:
            self: The test case instance.
        """
        with mock.patch.object(
            project_settings,
            "aplication_config",
            {
                "GOOGLE_OIDC_CLIENT_SECRET": "direct-secret",
                "GOOGLE_OIDC_CLIENT_SECRET_FILE": "/run/secrets/google-secret",
            },
        ):
            with self.assertRaises(ImproperlyConfigured):
                project_settings.get_secret_setting(
                    "GOOGLE_OIDC_CLIENT_SECRET",
                    "GOOGLE_OIDC_CLIENT_SECRET_FILE",
                )

    def test_rejects_relative_secret_file_path(self) -> None:
        """Reject ambiguous secret paths relative to the process directory.

        Args:
            self: The test case instance.
        """
        with mock.patch.object(
            project_settings,
            "aplication_config",
            {"GOOGLE_OIDC_CLIENT_SECRET_FILE": "relative-secret.txt"},
        ):
            with self.assertRaises(ImproperlyConfigured):
                project_settings.get_secret_setting(
                    "GOOGLE_OIDC_CLIENT_SECRET",
                    "GOOGLE_OIDC_CLIENT_SECRET_FILE",
                )

    def test_rejects_empty_multiline_and_oversized_secret_files(self) -> None:
        """Reject file contents that do not match the expected secret format.

        Args:
            self: The test case instance.
        """
        invalid_contents = (
            b"",
            b"first-line\nsecond-line",
            b"x" * (project_settings.MAX_SECRET_FILE_BYTES + 1),
        )

        with TemporaryDirectory() as temporary_directory:
            secret_path = Path(temporary_directory) / "invalid-secret.txt"

            for invalid_content in invalid_contents:
                # Each iteration of the loop is treated as an independent sub-test.
                with self.subTest(size=len(invalid_content)):
                    secret_path.write_bytes(invalid_content)

                    with mock.patch.object(
                        project_settings,
                        "aplication_config",
                        {"GOOGLE_OIDC_CLIENT_SECRET_FILE": str(secret_path)},
                    ):
                        with self.assertRaises(ImproperlyConfigured):
                            project_settings.get_secret_setting(
                                "GOOGLE_OIDC_CLIENT_SECRET",
                                "GOOGLE_OIDC_CLIENT_SECRET_FILE",
                            )
