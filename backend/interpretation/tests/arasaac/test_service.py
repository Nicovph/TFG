"""Test ARASAAC orchestration, fallback, and cache behavior."""

import asyncio
import inspect
import time
from unittest.mock import AsyncMock, Mock, call, patch

import httpx
from asgiref.sync import sync_to_async
from django.test import SimpleTestCase, override_settings

from ...arasaac import AvailablePictogram, VisualSupportResult, get_visual_support
from ...arasaac.service import _get_visual_support
from .helpers import ARASAAC_TEST_SETTINGS, SlowJsonStream


_CACHE_TEST_SETTINGS = {
    "ARASAAC_CACHE_TTL_SECONDS": 86_400,
    "ARASAAC_NOT_FOUND_CACHE_TTL_SECONDS": 900,
}


def _available_pictogram(concept: str) -> AvailablePictogram:
    """Build one validated synthetic provider result.

    Args:
        concept: Safe concept and matching display label.

    Returns:
        A fixed-origin available pictogram for service tests.
    """
    return AvailablePictogram(
        concept=concept,
        pictogram_id=9829,
        label=concept,
        image_url="https://static.arasaac.org/pictograms/9829/9829_300.png",
    )


@override_settings(**ARASAAC_TEST_SETTINGS)
class ArasaacServiceTests(SimpleTestCase):
    def test_public_lookup_exposes_only_concepts(self) -> None:
        """Keep test-only transport injection out of the public interface."""
        self.assertEqual(
            tuple(inspect.signature(get_visual_support).parameters),
            ("concepts",),
        )

    def test_zero_ttls_disable_cache_access(self) -> None:
        """Bypass cache reads and writes when both bounded TTLs are disabled."""
        cache = Mock()
        provider = AsyncMock(return_value=_available_pictogram("sin cache"))
        with patch(
            "backend.interpretation.arasaac.service.search_concept",
            provider,
        ):
            with patch(
                "backend.interpretation.arasaac.service.caches",
                {"arasaac": cache},
            ):
                result = _get_visual_support(concepts=("sin cache",))

        self.assertEqual(result.status, "complete")
        cache.get.assert_not_called()
        cache.set.assert_not_called()

    @override_settings(**_CACHE_TEST_SETTINGS)
    def test_available_result_is_cached_for_one_day_and_reused(self) -> None:
        """Reuse one validated result without exposing the concept in its key."""
        cache = Mock()
        cache.get.return_value = None
        cache.set.return_value = True
        provider = AsyncMock(return_value=_available_pictogram("amistad"))
        with patch(
            "backend.interpretation.arasaac.service.search_concept",
            provider,
        ):
            with patch(
                "backend.interpretation.arasaac.service.caches",
                {"arasaac": cache},
            ):
                first = _get_visual_support(concepts=("amistad",))
                key, cached_value = cache.set.call_args.args
                cache.get.return_value = cached_value
                second = _get_visual_support(concepts=("amistad",))

        provider.assert_awaited_once()
        self.assertEqual(first, second)
        self.assertTrue(key.startswith("arasaac-pictogram-v1:"))
        self.assertNotIn("amistad", key)
        self.assertEqual(cache.get.call_args_list, [call(key), call(key)])
        self.assertEqual(
            set(cached_value),
            {"pictogram_id", "label", "plural"},
        )
        cache.set.assert_called_once_with(
            key,
            cached_value,
            timeout=86_400,
        )

    @override_settings(**_CACHE_TEST_SETTINGS)
    def test_not_found_is_cached_for_fifteen_minutes_and_reused(self) -> None:
        """Reuse a short-lived negative result without a second provider call."""
        cache = Mock()
        cache.get.return_value = None
        cache.set.return_value = True
        provider = AsyncMock(return_value=None)
        with patch(
            "backend.interpretation.arasaac.service.search_concept",
            provider,
        ):
            with patch(
                "backend.interpretation.arasaac.service.caches",
                {"arasaac": cache},
            ):
                first = _get_visual_support(concepts=("ausente",))
                key, cached_value = cache.set.call_args.args
                cache.get.return_value = cached_value
                second = _get_visual_support(concepts=("ausente",))

        provider.assert_awaited_once()
        self.assertEqual(first, second)
        self.assertEqual(cached_value, "not_found")
        cache.set.assert_called_once_with(
            key,
            cached_value,
            timeout=900,
        )

    @override_settings(**_CACHE_TEST_SETTINGS)
    def test_invalid_cached_value_is_replaced_from_the_provider(self) -> None:
        """Reject invalid cached metadata and store a validated replacement."""
        cache = Mock()
        cache.get.return_value = {
            "pictogram_id": 9829,
            "label": "<script>",
            "plural": False,
        }
        cache.set.return_value = True
        provider = AsyncMock(return_value=_available_pictogram("seguridad"))
        with patch(
            "backend.interpretation.arasaac.service.search_concept",
            provider,
        ):
            with patch(
                "backend.interpretation.arasaac.service.caches",
                {"arasaac": cache},
            ):
                result = _get_visual_support(concepts=("seguridad",))

        provider.assert_awaited_once()
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.items[0].label, "seguridad")
        self.assertEqual(
            cache.set.call_args.args[1],
            {"pictogram_id": 9829, "label": "seguridad", "plural": False},
        )

    @override_settings(**_CACHE_TEST_SETTINGS)
    def test_cache_failures_preserve_valid_provider_results(self) -> None:
        """Treat optional cache read and write failures as sanitized misses."""
        private_detail = "redis://private-user:private-password@cache.internal"

        for operation in ("read", "write"):
            with self.subTest(operation=operation):
                cache = Mock()
                cache.get.return_value = None
                cache.set.return_value = True
                getattr(cache, "get" if operation == "read" else "set").side_effect = (
                    RuntimeError(private_detail)
                )
                provider = AsyncMock(
                    return_value=_available_pictogram("concepto privado")
                )

                with patch(
                    "backend.interpretation.arasaac.service.search_concept",
                    provider,
                ):
                    with patch(
                        "backend.interpretation.arasaac.service.caches",
                        {"arasaac": cache},
                    ):
                        with self.assertLogs(
                            "backend.interpretation.arasaac",
                            level="WARNING",
                        ) as captured:
                            result = _get_visual_support(
                                concepts=("concepto privado",),
                            )

                rendered_logs = " ".join(captured.output)
                provider.assert_awaited_once()
                self.assertEqual(result.status, "complete")
                self.assertIn(f"operation={operation}", rendered_logs)
                self.assertNotIn("concepto privado", rendered_logs)
                self.assertNotIn(private_detail, rendered_logs)

    @override_settings(**_CACHE_TEST_SETTINGS)
    def test_timeout_fails_fast_and_redacts_concepts(self) -> None:
        """Stop after one failure while preserving a later cached result."""
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Raise one transport timeout containing private diagnostic text.

            Args:
                request: Fixed-origin request attached to the timeout.

            Raises:
                ReadTimeout: Always, to exercise safe degradation.
            """
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout(
                "private concepto reservado",
                request=request,
            )

        cache = Mock()
        cache.get.side_effect = [
            None,
            {"pictogram_id": 9829, "label": "segundo concepto", "plural": False},
        ]
        cache.set.return_value = True
        with patch(
            "backend.interpretation.arasaac.service.caches",
            {"arasaac": cache},
        ):
            with self.assertLogs(
                "backend.interpretation.arasaac",
                level="WARNING",
            ) as captured:
                result = _get_visual_support(
                    concepts=("concepto reservado", "segundo concepto"),
                    transport=httpx.MockTransport(handler),
                )

        self.assertEqual(calls, 1)
        self.assertEqual(
            [item.status for item in result.items],
            ["temporarily_unavailable", "available"],
        )
        self.assertEqual(
            [item.concept for item in result.items],
            ["concepto reservado", "segundo concepto"],
        )
        rendered_logs = " ".join(captured.output)
        self.assertIn("error_type=timeout", rendered_logs)
        self.assertNotIn("concepto reservado", rendered_logs)
        self.assertNotIn("private", rendered_logs)
        cache.set.assert_not_called()

    @override_settings(
        ARASAAC_CONNECT_TIMEOUT_SECONDS=1,
        ARASAAC_READ_TIMEOUT_SECONDS=1,
        ARASAAC_TOTAL_TIMEOUT_SECONDS=0.05,
    )
    def test_total_budget_bounds_a_frequent_slow_drip_stream(self) -> None:
        """Enforce wall-clock budget even while fragments keep arriving."""
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                stream=SlowJsonStream(),
                headers={"Content-Type": "application/json"},
            )
        )

        started = time.monotonic()
        with self.assertLogs(
            "backend.interpretation.arasaac",
            level="WARNING",
        ) as captured:
            result = _get_visual_support(
                concepts=("concepto",),
                transport=transport,
            )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        self.assertEqual(result.items[0].status, "temporarily_unavailable")
        self.assertIn("error_type=total_timeout", " ".join(captured.output))

    def test_sync_lookup_runs_under_django_asgi_adapter(self) -> None:
        """Avoid deadlock when an ASGI server adapts the synchronous view."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Return an immediate valid lookup response.

            Args:
                _request: Request created by the ARASAAC client.

            Returns:
                A synthetic exact pictogram match.
            """
            return httpx.Response(
                200,
                json=[
                    {
                        "_id": 9829,
                        "keywords": [{"keyword": "futuro"}],
                    }
                ],
            )

        async def run_lookup_on_active_loop() -> VisualSupportResult:
            """Model an ASGI event loop that continues serving other work."""
            lookup_task = asyncio.create_task(
                sync_to_async(_get_visual_support, thread_sensitive=True)(
                    concepts=("futuro",),
                    transport=httpx.MockTransport(handler),
                )
            )
            while not lookup_task.done():
                await asyncio.sleep(0.005)
            return await lookup_task

        result = asyncio.run(run_lookup_on_active_loop())

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.items[0].pictogram_id, 9829)

    @override_settings(
        ARASAAC_CONNECT_TIMEOUT_SECONDS=1,
        ARASAAC_READ_TIMEOUT_SECONDS=1,
        ARASAAC_TOTAL_TIMEOUT_SECONDS=0.05,
    )
    def test_slow_degradation_runs_under_django_asgi_adapter(self) -> None:
        """Keep the frequent slow-drip fallback compatible with ASGI adaptation."""
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                stream=SlowJsonStream(),
                headers={"Content-Type": "application/json"},
            )
        )

        async def run_lookup_on_active_loop() -> VisualSupportResult:
            """Model an ASGI event loop that continues serving other work."""
            lookup_task = asyncio.create_task(
                sync_to_async(_get_visual_support, thread_sensitive=True)(
                    concepts=("concepto",),
                    transport=transport,
                )
            )
            while not lookup_task.done():
                await asyncio.sleep(0.005)
            return await lookup_task

        started = time.monotonic()
        with self.assertLogs(
            "backend.interpretation.arasaac",
            level="WARNING",
        ):
            result = asyncio.run(run_lookup_on_active_loop())

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(result.items[0].status, "temporarily_unavailable")

    def test_empty_and_invalid_concept_lists_never_call_network(self) -> None:
        """Return no-op state for empty input and reject bypassed policy values."""
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            """Fail the test if invalid input reaches the network.

            Args:
                _request: Unexpected request that must never be sent.

            Raises:
                AssertionError: Always, because no call is expected.
            """
            nonlocal calls
            calls += 1
            raise AssertionError("No debía realizarse una petición externa.")

        transport = httpx.MockTransport(handler)
        empty_result = _get_visual_support(concepts=(), transport=transport)
        self.assertEqual(empty_result.status, "not_requested")

        invalid_cases: tuple[object, ...] = (
            "concepto",
            ("duplicado", "DUPLICADO"),
            ("concepto",) * 6,
            ("../destino",),
            (True,),
        )
        for concepts in invalid_cases:
            with self.subTest(concepts=concepts):
                with self.assertRaises(ValueError):
                    _get_visual_support(
                        concepts=concepts,  # type: ignore[arg-type]
                        transport=transport,
                    )

        self.assertEqual(calls, 0)
