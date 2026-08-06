"""Focused tests for interpretation startup configuration checks."""

from django.test import SimpleTestCase, override_settings

from ..checks import (
    check_llm_request_fits_empty_quotas,
    check_llm_transient_cache,
)


LOCAL_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "interpretation-check-tests",
    }
}
TOKEN_QUOTA_SETTINGS = (
    "LLM_USER_TOKENS_PER_MINUTE",
    "LLM_USER_TOKENS_PER_DAY",
    "LLM_GLOBAL_TOKENS_PER_MINUTE",
    "LLM_GLOBAL_TOKENS_PER_DAY",
)


class InterpretationConfigurationCheckTests(SimpleTestCase):
    """Verify cache and quota invariants without starting external services."""

    @override_settings(
        CACHES=LOCAL_CACHE,
        LLM_DUPLICATE_CACHE_ALIAS="default",
        LLM_REQUIRE_SHARED_DUPLICATE_CACHE=False,
        LLM_USER_TOKENS_PER_MINUTE=1_000_000,
        LLM_USER_TOKENS_PER_DAY=1_000_000,
        LLM_GLOBAL_TOKENS_PER_MINUTE=1_000_000,
        LLM_GLOBAL_TOKENS_PER_DAY=1_000_000,
    )
    def test_valid_cache_and_quota_configuration_returns_no_errors(self) -> None:
        """Accept a known cache alias and quotas above every valid request."""
        self.assertEqual(check_llm_transient_cache(None), [])
        self.assertEqual(check_llm_request_fits_empty_quotas(None), [])

    @override_settings(
        CACHES=LOCAL_CACHE,
        LLM_DUPLICATE_CACHE_ALIAS="missing",
        LLM_REQUIRE_SHARED_DUPLICATE_CACHE=False,
    )
    def test_unknown_transient_cache_alias_returns_closed_error(self) -> None:
        """Report an unknown alias without exposing cache connection details."""
        errors = check_llm_transient_cache(None)

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "interpretation.E001")
        self.assertIn("LLM_DUPLICATE_CACHE_ALIAS", errors[0].msg)

    @override_settings(
        CACHES=LOCAL_CACHE,
        LLM_DUPLICATE_CACHE_ALIAS="default",
        LLM_REQUIRE_SHARED_DUPLICATE_CACHE=True,
    )
    def test_local_cache_is_rejected_when_shared_cache_is_required(self) -> None:
        """Reject process-local coordination when deployment requires sharing."""
        errors = check_llm_transient_cache(None)

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "interpretation.E001")
        self.assertIn("caché compartida", errors[0].msg)

    def test_each_token_quota_below_maximum_reservation_is_reported(self) -> None:
        """Identify each independently undersized token quota setting."""
        valid_quotas = {
            setting_name: 1_000_000
            for setting_name in TOKEN_QUOTA_SETTINGS
        }

        for setting_name in TOKEN_QUOTA_SETTINGS:
            with self.subTest(setting_name=setting_name):
                # One token cannot contain the fixed prompt and completion
                # budget, while the other large quotas isolate this setting.
                configured_quotas = {
                    **valid_quotas,
                    setting_name: 1,
                }

                with override_settings(**configured_quotas):
                    errors = check_llm_request_fits_empty_quotas(None)

                self.assertEqual(len(errors), 1)
                self.assertEqual(errors[0].id, "interpretation.E002")
                self.assertIn(setting_name, errors[0].msg)
