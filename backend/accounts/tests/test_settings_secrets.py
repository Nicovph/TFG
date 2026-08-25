"""Tests for strict security settings and backend secret loading."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from Traductor_TEA import settings as project_settings


class BooleanSecuritySettingTests(SimpleTestCase):
    """Validate strict Boolean parsing for security-sensitive settings."""

    def test_django_debug_accepts_explicit_false(self) -> None:
        """Allow Compose to disable Django debug mode with a strict literal.

        Args:
            self: The test case instance.
        """
        with mock.patch.object(
            project_settings,
            "aplication_config",
            {"DJANGO_DEBUG": "false"},
        ):
            debug_enabled = project_settings.get_boolean_setting(
                "DJANGO_DEBUG",
                default=True,
            )

        self.assertFalse(debug_enabled)

    def test_django_debug_rejects_ambiguous_value(self) -> None:
        """Fail closed when Django debug mode is not a recognized Boolean.

        Args:
            self: The test case instance.
        """
        with (
            mock.patch.object(
                project_settings,
                "aplication_config",
                {"DJANGO_DEBUG": "sometimes"},
            ),
            self.assertRaisesRegex(ImproperlyConfigured, "DJANGO_DEBUG"),
        ):
            project_settings.get_boolean_setting(
                "DJANGO_DEBUG",
                default=True,
            )


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

    def test_reads_secret_from_local_default_file(self) -> None:
        """Use the ignored local file when no explicit source is configured.

        Args:
            self: The test case instance.
        """
        with TemporaryDirectory() as temporary_directory:
            secret_path = Path(temporary_directory) / "local-secret.txt"
            secret_path.write_text("local-file-secret\n", encoding="utf-8")

            with mock.patch.object(project_settings, "aplication_config", {}):
                value = project_settings.get_secret_setting(
                    "DJANGO_SECRET_KEY",
                    "DJANGO_SECRET_KEY_FILE",
                    default_file=secret_path,
                )

        self.assertEqual(value, "local-file-secret")

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


class DjangoSecretKeyTests(SimpleTestCase):
    """Validate role-aware Django signing-key configuration."""

    def test_application_profile_accepts_strong_external_key(self) -> None:
        """Use a strong explicitly configured key for the HTTP application.

        Args:
            self: The test case instance.
        """
        configured_key = "test-only-application-key-" + ("a1B2" * 16)

        with (
            mock.patch.object(
                project_settings,
                "aplication_config",
                {"DJANGO_SECRET_KEY": configured_key},
            ),
            mock.patch.object(
                project_settings,
                "DATABASE_PROFILE",
                "app",
            ),
        ):
            value = project_settings.get_django_secret_key()

        self.assertEqual(value, configured_key)

    def test_application_profile_rejects_missing_secret_key(self) -> None:
        """Fail startup when the HTTP application has no stable signing key.

        Args:
            self: The test case instance.
        """
        with TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing-secret.txt"

            with (
                mock.patch.object(project_settings, "aplication_config", {}),
                mock.patch.object(
                    project_settings,
                    "DATABASE_PROFILE",
                    "app",
                ),
                self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "DJANGO_SECRET_KEY",
                ),
            ):
                project_settings.get_django_secret_key(
                    local_secret_file=missing_path,
                )

    def test_offline_profiles_generate_independent_ephemeral_key(self) -> None:
        """Avoid distributing the stable application key to offline tasks.

        Args:
            self: The test case instance.
        """
        ephemeral_key = "test-only-ephemeral-key-" + ("a1B2" * 16)

        with TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing-secret.txt"

            with mock.patch.object(
                project_settings.secrets,
                "token_urlsafe",
                return_value=ephemeral_key,
            ) as generate_key:
                for profile_name in ("migrate", "test"):
                    with (
                        self.subTest(profile=profile_name),
                        mock.patch.object(
                            project_settings,
                            "aplication_config",
                            {},
                        ),
                        mock.patch.object(
                            project_settings,
                            "DATABASE_PROFILE",
                            profile_name,
                        ),
                    ):
                        value = project_settings.get_django_secret_key(
                            local_secret_file=missing_path,
                        )
                        self.assertEqual(value, ephemeral_key)

        self.assertEqual(generate_key.call_count, 2)
        # Verify that the last call was made with the argument 64 (secrets.urlsafe(64)).
        generate_key.assert_called_with(64)

    def test_rejects_weak_configured_secret_key(self) -> None:
        """Reject known development-style keys before Django starts.

        Args:
            self: The test case instance.
        """
        with TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing-secret.txt"

            with (
                mock.patch.object(
                    project_settings,
                    "aplication_config",
                    {"DJANGO_SECRET_KEY": "django-insecure-" + ("x" * 64)},
                ),
                mock.patch.object(
                    project_settings,
                    "DATABASE_PROFILE",
                    "app",
                ),
                self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "django-insecure-",
                ),
            ):
                project_settings.get_django_secret_key(
                    local_secret_file=missing_path,
                )
