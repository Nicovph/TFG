import asyncio
import inspect
import time

import httpx
from asgiref.sync import sync_to_async
from django.test import SimpleTestCase, override_settings

from ...arasaac import VisualSupportResult, get_visual_support
from ...arasaac.service import _get_visual_support
from .helpers import ARASAAC_TEST_SETTINGS, SlowJsonStream


@override_settings(**ARASAAC_TEST_SETTINGS)
class ArasaacServiceTests(SimpleTestCase):
    def test_public_lookup_exposes_only_concepts(self) -> None:
        """Keep test-only transport injection out of the public interface."""
        self.assertEqual(
            tuple(inspect.signature(get_visual_support).parameters),
            ("concepts",),
        )

    def test_timeout_fails_fast_and_redacts_concepts(self) -> None:
        """Use one failed call and mark every remaining concept unavailable."""
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
            ["temporarily_unavailable", "temporarily_unavailable"],
        )
        rendered_logs = " ".join(captured.output)
        self.assertIn("error_type=timeout", rendered_logs)
        self.assertNotIn("concepto reservado", rendered_logs)
        self.assertNotIn("private", rendered_logs)

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
