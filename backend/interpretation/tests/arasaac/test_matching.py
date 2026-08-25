"""Test deterministic pictogram matching without adding semantic meaning."""

import httpx
from django.test import SimpleTestCase, override_settings

from ...arasaac import AvailablePictogram
from ...arasaac.contracts import ArasaacPictogram
from ...arasaac.matching import select_pictogram
from ...arasaac.service import _get_visual_support
from .helpers import ARASAAC_TEST_SETTINGS


@override_settings(**ARASAAC_TEST_SETTINGS)
class ArasaacMatchingTests(SimpleTestCase):
    """Verify literal concept matching and bounded article equivalence."""

    def test_normalizes_comparison_and_preserves_provider_order_for_ties(
        self,
    ) -> None:
        """Normalize only comparison keys and retain provider order for ties."""
        concept = "CAFE\u0301"
        candidates = [
            ArasaacPictogram.model_validate(
                {"_id": pictogram_id, "keywords": [{"keyword": "café"}]}
            )
            for pictogram_id in (9829, 99999)
        ]

        result = select_pictogram(
            concept=concept,
            candidates=candidates,
            allow_inserted_article=False,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.pictogram_id, 9829)
        self.assertEqual(result.concept, concept)

    def test_selects_full_labels_and_rejects_added_meaning(self) -> None:
        """Use exact search first and broaden only for an omitted article."""
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Return representative official response shapes by search path.

            Args:
                request: Request created by the fixed ARASAAC client.

            Returns:
                A synthetic JSON response for the requested concept.
            """
            requests.append(request)
            timeouts = request.extensions["timeout"]
            self.assertGreater(timeouts["connect"], 0)
            self.assertLessEqual(timeouts["connect"], 2)
            self.assertGreater(timeouts["read"], 0)
            self.assertLessEqual(timeouts["read"], 3)
            path_parts = request.url.raw_path.decode("ascii").rsplit("/", 2)
            operation, search_text = path_parts[-2:]
            responses: dict[tuple[str, str], list[dict[str, object]]] = {
                ("search", "abrir%20puerta"): [
                    {
                        "_id": 4687,
                        "keywords": [
                            {"keyword": "llamar a la puerta", "plural": ""}
                        ],
                    },
                    {
                        "_id": 22056,
                        "keywords": [{"keyword": "Puerta de Alcalá"}],
                    },
                    {
                        "_id": 22058,
                        "keywords": [{"keyword": "Puerta de Brandeburgo"}],
                    },
                    {
                        "_id": 24597,
                        "keywords": [{"keyword": "abrir la puerta"}],
                        "url": "http://169.254.169.254/private",
                    },
                ],
                ("bestsearch", "futuro"): [
                    {
                        "_id": 9829,
                        "keywords": [{"keyword": "futuro", "plural": ""}],
                    }
                ],
                ("bestsearch", "lenguaje"): [
                    {
                        "_id": 10259,
                        "keywords": [
                            {"keyword": "lenguaje", "plural": "lenguajes"}
                        ],
                    }
                ],
                ("bestsearch", "coches"): [
                    {
                        "_id": 2391,
                        "keywords": [{"keyword": "coche", "plural": "coches"}],
                    }
                ],
            }
            key = (operation, search_text)
            if key == ("bestsearch", "abrir%20puerta"):
                return httpx.Response(
                    404,
                    json=[],
                    headers={"Set-Cookie": "provider_tracking=blocked"},
                )
            if key == ("bestsearch", "ataque"):
                return httpx.Response(404, json=[])
            return httpx.Response(
                200,
                json=responses[key],
            )

        result = _get_visual_support(
            concepts=(
                "abrir puerta",
                "ataque",
                "futuro",
                "lenguaje",
                "coches",
            ),
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(
            [item.status for item in result.items],
            [
                "available",
                "not_found",
                "available",
                "available",
                "available",
            ],
        )
        self.assertEqual(result.items[0].pictogram_id, 24597)
        self.assertEqual(result.items[0].label, "abrir la puerta")
        self.assertEqual(
            result.items[0].image_url,
            "https://static.arasaac.org/pictograms/24597/24597_300.png",
        )
        self.assertEqual(result.items[2].pictogram_id, 9829)
        self.assertEqual(result.items[3].pictogram_id, 10259)
        self.assertEqual(
            result.items[4].image_url,
            "https://static.arasaac.org/pictograms/2391/2391_plural_300.png",
        )
        self.assertIsNotNone(result.attribution)
        self.assertIn("Sergio Palao", result.attribution.text)

        self.assertEqual(len(requests), 6)
        self.assertEqual(
            sum(
                "/search/" in request.url.raw_path.decode("ascii")
                for request in requests
            ),
            1,
        )
        for request in requests:
            self.assertEqual(request.url.scheme, "https")
            self.assertEqual(request.url.host, "api.arasaac.org")
            self.assertEqual(request.headers["Accept"], "application/json")
            self.assertEqual(request.headers["Accept-Encoding"], "identity")
            self.assertNotIn("Authorization", request.headers)
            self.assertNotIn("Cookie", request.headers)

    def test_article_equivalence_is_directional_and_literal_match_wins(self) -> None:
        """Reject leading-article meaning changes and prefer exact later labels."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return narrow article edge cases for the requested search path."""
            operation, search_text = request.url.raw_path.decode(
                "ascii"
            ).rsplit("/", 2)[-2:]
            if operation == "bestsearch":
                return httpx.Response(404, json=[])
            payloads = {
                "abrir%20puerta": [
                    {
                        "_id": 24597,
                        "keywords": [{"keyword": "abrir la puerta"}],
                    },
                    {
                        "_id": 99999,
                        "keywords": [{"keyword": "abrir puerta"}],
                    },
                ],
            }
            return httpx.Response(200, json=payloads[search_text])

        result = _get_visual_support(
            concepts=("salvador", "el", "abrir puerta"),
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(
            [item.status for item in result.items],
            ["not_found", "not_found", "available"],
        )
        exact_item = result.items[2]
        self.assertIsInstance(exact_item, AvailablePictogram)
        assert isinstance(exact_item, AvailablePictogram)
        self.assertEqual(exact_item.pictogram_id, 99999)
