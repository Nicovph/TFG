"""Test the bounded ARASAAC HTTP trust boundary."""

import traceback
from collections.abc import Callable

import httpx
from django.test import SimpleTestCase, override_settings

from ...arasaac.client import (
    ARASAAC_API_ORIGIN,
    _ArasaacHttpStatusError,
    _ArasaacResponseError,
    search_concept,
)
from ...arasaac.service import _get_visual_support
from .helpers import (
    ARASAAC_TEST_SETTINGS,
    ExcessiveJsonStream,
    UnreadableJsonStream,
)


@override_settings(**ARASAAC_TEST_SETTINGS)
class ArasaacClientTests(SimpleTestCase):
    async def test_request_never_inherits_client_redirect_policy(self) -> None:
        """Refuse redirects even when the injected client would follow them."""
        requested_hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record destinations and simulate an external redirect.

            Args:
                request: Synthetic request issued by the ARASAAC client.

            Returns:
                A redirect first and an empty response if it is followed.
            """
            requested_hosts.append(request.url.host)
            if len(requested_hosts) == 1:
                return httpx.Response(
                    302,
                    headers={"Location": "https://other.example/collect"},
                )
            return httpx.Response(200, json=[])

        async with httpx.AsyncClient(
            base_url=ARASAAC_API_ORIGIN,
            follow_redirects=True,
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(_ArasaacHttpStatusError):
                await search_concept(client=client, concept="concepto")

        self.assertEqual(requested_hosts, ["api.arasaac.org"])

    async def test_external_validation_errors_hide_original_causes(self) -> None:
        """Suppress untrusted parser details from standard tracebacks."""
        marker = "synthetic-provider-detail"
        invalid_responses: tuple[tuple[str, httpx.Response], ...] = (
            (
                "invalid_json",
                httpx.Response(
                    200,
                    content=f'{{"{marker}":'.encode(),
                    headers={"Content-Type": "application/json"},
                ),
            ),
            (
                "invalid_schema",
                httpx.Response(
                    200,
                    json=[{"_id": marker, "keywords": []}],
                ),
            ),
        )

        for error_code, response in invalid_responses:
            with self.subTest(error_code=error_code):
                async with httpx.AsyncClient(
                    base_url=ARASAAC_API_ORIGIN,
                    transport=httpx.MockTransport(
                        lambda _request: response
                    ),
                ) as client:
                    with self.assertRaises(_ArasaacResponseError) as raised:
                        await search_concept(client=client, concept="concepto")

                self.assertEqual(str(raised.exception), error_code)
                self.assertIsNone(raised.exception.__cause__)
                self.assertNotIn(
                    marker,
                    "".join(traceback.format_exception(raised.exception)),
                )

    def test_valid_empty_404_is_not_a_provider_failure(self) -> None:
        """Treat the API's current 404 plus empty-array shape as not found."""
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(404, json=[])
        )

        result = _get_visual_support(
            concepts=("concepto ausente",),
            transport=transport,
        )

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.items[0].status, "not_found")
        self.assertIsNone(result.attribution)
        self.assertIn("interpretación de texto", result.message)

    def test_collection_sizes_are_bounded_by_bytes_not_arbitrary_counts(
        self,
    ) -> None:
        """Accept over 256 candidates and over 32 keywords within the byte ceiling."""
        payload = [
            {"_id": index + 1, "keywords": [{"keyword": "otro"}]}
            for index in range(256)
        ]
        payload.append(
            {
                "_id": 9829,
                "keywords": [
                    *({"keyword": "otro"} for _ in range(32)),
                    {"keyword": "futuro"},
                ],
            }
        )

        result = _get_visual_support(
            concepts=("futuro",),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json=payload)
            ),
        )

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.items[0].pictogram_id, 9829)

    def test_invalid_external_responses_degrade_without_redirecting(self) -> None:
        """Reject active, malformed, excessive, and schema-invalid responses."""
        invalid_responses: tuple[
            tuple[str, Callable[[], httpx.Response]],
            ...,
        ] = (
            (
                "active_content",
                lambda: httpx.Response(
                    200,
                    text="<script>alert(1)</script>",
                    headers={"Content-Type": "text/html"},
                ),
            ),
            (
                "malformed_json",
                lambda: httpx.Response(
                    200,
                    content=b"{",
                    headers={"Content-Type": "application/json"},
                ),
            ),
            (
                "deeply_nested_json",
                lambda: httpx.Response(
                    200,
                    content=(b"[" * 2_000) + b"0" + (b"]" * 2_000),
                    headers={"Content-Type": "application/json"},
                ),
            ),
            (
                "unexpected_compression",
                lambda: httpx.Response(
                    200,
                    stream=UnreadableJsonStream(),
                    headers={
                        "Content-Type": "application/json",
                        "Content-Encoding": "gzip",
                    },
                ),
            ),
            (
                "boolean_identifier",
                lambda: httpx.Response(
                    200,
                    json=[
                        {
                            "_id": True,
                            "keywords": [{"keyword": "concepto"}],
                        }
                    ],
                ),
            ),
            (
                "unsafe_integer_identifier",
                lambda: httpx.Response(
                    200,
                    json=[
                        {
                            "_id": 2**53,
                            "keywords": [{"keyword": "concepto"}],
                        }
                    ],
                ),
            ),
            (
                "excessive_body",
                lambda: httpx.Response(
                    200,
                    stream=ExcessiveJsonStream(),
                    headers={"Content-Type": "application/json"},
                ),
            ),
            (
                "redirect",
                lambda: httpx.Response(
                    302,
                    headers={"Location": "http://169.254.169.254/latest"},
                ),
            ),
        )

        for case_name, response_factory in invalid_responses:
            with self.subTest(case_name=case_name):
                calls = 0

                def handler(_request: httpx.Request) -> httpx.Response:
                    """Count one request and return the selected invalid response.

                    Args:
                        _request: Fixed-origin request, unused in this case.

                    Returns:
                        The invalid response associated with the subtest.
                    """
                    nonlocal calls
                    calls += 1
                    return response_factory()

                with self.assertLogs(
                    "backend.interpretation.arasaac",
                    level="WARNING",
                ) as captured:
                    result = _get_visual_support(
                        concepts=("concepto",),
                        transport=httpx.MockTransport(handler),
                    )

                self.assertEqual(calls, 1)
                self.assertEqual(result.status, "unavailable")
                self.assertEqual(
                    result.items[0].status,
                    "temporarily_unavailable",
                )
                rendered_logs = " ".join(captured.output)
                self.assertNotIn("169.254.169.254", rendered_logs)
                self.assertNotIn("<script>", rendered_logs)
