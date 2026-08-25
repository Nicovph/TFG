"""Tests for Google OpenID Connect ID token validation."""

from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from google.auth.exceptions import TransportError

from .. import services
from .helpers import fake_jwt, valid_claims


@override_settings(
    DEBUG=True,
    GOOGLE_OIDC_CLIENT_ID="client-id.apps.googleusercontent.com",
    GOOGLE_OIDC_CLIENT_SECRET="test-client-secret",
    GOOGLE_OIDC_REDIRECT_URI="http://testserver/api/auth/google/callback/",
)
class GoogleOIDCTokenValidationTests(TestCase):
    """Verify local validation around the maintained Google token verifier."""

    def setUp(self) -> None:
        """Build the Google OIDC config used by token validation tests.

        Args:
            self: The test case instance.
        """
        self.config = services.get_google_oidc_config()

    def _assert_claims_rejected(self, claims: dict[str, object]) -> None:
        """Assert that validation rejects mocked Google ID token claims.

        Args:
            claims: The verified claims that the local validator must reject.

        Raises:
            AssertionError: If the claims are accepted unexpectedly.
        """
        # The return value are the claims that are passed as an argument to the function.
        with mock.patch(
            "backend.accounts.services.token_validation.verify_google_id_token_signature",
            return_value=claims,
        ):
            with self.assertRaises(services.GoogleOIDCTokenError):
                services.validate_google_id_token(
                    id_token=fake_jwt(),
                    expected_nonce="nonce-value",
                    expected_client_id="client-id.apps.googleusercontent.com",
                    config=self.config,
                )

    def test_validate_id_token_accepts_expected_claims(self) -> None:
        """Accept the signed token only when required claims match.

        Args:
            self: The test case instance.
        """
        claims = valid_claims(nonce="nonce-value")

        with mock.patch(
            "backend.accounts.services.token_validation.verify_google_id_token_signature",
            return_value=claims,
        ) as verifier:
            validated_claims = services.validate_google_id_token(
                id_token=fake_jwt(),
                expected_nonce="nonce-value",
                expected_client_id="client-id.apps.googleusercontent.com",
                config=self.config,
            )

        self.assertEqual(validated_claims["sub"], "google-subject-flow")
        verifier.assert_called_once_with(
            id_token=fake_jwt(),
            audience="client-id.apps.googleusercontent.com",
            timeout_seconds=self.config.timeout_seconds,
        )

    def test_validate_id_token_rejects_nonce_issuer_audience_and_expiry(self) -> None:
        """Reject ID tokens with mismatched security claims.

        Args:
            self: The test case instance.
        """
        now = int(timezone.now().timestamp())
        # The asterisks are used to create a dictionary from the valid_claims values ​​and overwrite the keys specified here.
        cases = [
            ("bad-nonce", {**valid_claims(nonce="wrong-nonce")}),
            (
                "bad-issuer",
                {**valid_claims(nonce="nonce-value"), "iss": "https://evil.example"},
            ),
            (
                "bad-audience",
                {**valid_claims(nonce="nonce-value"), "aud": "other-client"},
            ),
            (
                "expired",
                {**valid_claims(nonce="nonce-value"), "exp": now - 1},
            ),
        ]

        for _name, claims in cases:
            with self.subTest(case=_name):
                with mock.patch(
                    "backend.accounts.services.token_validation.verify_google_id_token_signature",
                    return_value=claims,
                ):
                    with self.assertRaises(services.GoogleOIDCTokenError):
                        services.validate_google_id_token(
                            id_token=fake_jwt(),
                            expected_nonce="nonce-value",
                            expected_client_id="client-id.apps.googleusercontent.com",
                            config=self.config,
                        )

    def test_validate_id_token_rejects_future_issued_at(self) -> None:
        """Reject ID tokens issued beyond the configured clock skew.

        Args:
            self: The test case instance.
        """
        now = int(timezone.now().timestamp())
        claims = {
            **valid_claims(nonce="nonce-value"),
            "iat": now + self.config.max_iat_skew_seconds + 1,
        }

        self._assert_claims_rejected(claims)

    def test_validate_id_token_rejects_boolean_lifetime_claims(self) -> None:
        """Reject boolean exp and iat values despite bool being an int subclass.

        Args:
            self: The test case instance.
        """
        cases = [
            (
                "boolean-exp",
                {**valid_claims(nonce="nonce-value"), "exp": True},
                "Claim OIDC obligatorio ausente: exp.",
            ),
            (
                "boolean-iat",
                {**valid_claims(nonce="nonce-value"), "iat": True},
                "Claim OIDC obligatorio ausente: iat.",
            ),
        ]

        for name, claims, message in cases:
            with self.subTest(case=name):
                with mock.patch(
                    "backend.accounts.services.token_validation.verify_google_id_token_signature",
                    return_value=claims,
                ):
                    with self.assertRaisesMessage(
                        services.GoogleOIDCTokenError,
                        message,
                    ):
                        services.validate_google_id_token(
                            id_token=fake_jwt(),
                            expected_nonce="nonce-value",
                            expected_client_id="client-id.apps.googleusercontent.com",
                            config=self.config,
                        )

    def test_validate_id_token_rejects_invalid_authorized_party(self) -> None:
        """Reject azp values that do not bind the ID token to this client.

        Args:
            self: The test case instance.
        """
        expected_client = "client-id.apps.googleusercontent.com"
        other_client = "other-client.apps.googleusercontent.com"
        cases = [
            (
                "missing-azp-with-multiple-audiences",
                {
                    **valid_claims(nonce="nonce-value"),
                    "aud": [expected_client, other_client],
                },
            ),
            (
                "wrong-azp-with-multiple-audiences",
                {
                    **valid_claims(nonce="nonce-value"),
                    "aud": [expected_client, other_client],
                    "azp": other_client,
                },
            ),
            (
                "wrong-azp-with-single-audience",
                {
                    **valid_claims(nonce="nonce-value"),
                    "azp": other_client,
                },
            ),
        ]

        for name, claims in cases:
            with self.subTest(case=name):
                self._assert_claims_rejected(claims)

    def test_validate_id_token_rejects_invalid_subject_claims(self) -> None:
        """Reject subject claims that cannot identify a valid federated user.

        Args:
            self: The test case instance.
        """
        claims_without_subject = valid_claims(nonce="nonce-value")
        del claims_without_subject["sub"]
        cases = [
            ("missing-sub", claims_without_subject),
            ("empty-sub", {**valid_claims(nonce="nonce-value"), "sub": ""}),
            ("non-string-sub", {**valid_claims(nonce="nonce-value"), "sub": 12345}),
            (
                "invalid-format-sub",
                {**valid_claims(nonce="nonce-value"), "sub": "invalid subject"},
            ),
        ]

        for name, claims in cases:
            with self.subTest(case=name):
                self._assert_claims_rejected(claims)

    def test_validate_id_token_rejects_malformed_jwt_header(self) -> None:
        """Reject malformed JWTs before calling signature verification.

        Args:
            self: The test case instance.
        """
        cases = [
            ("missing-segment", "header.payload"),
            ("non-json-header", "bm90LWpzb24.payload.signature"),
            ("non-object-header", "W10.payload.signature"),
        ]

        for name, token in cases:
            with self.subTest(case=name):
                with mock.patch(
                    "backend.accounts.services.token_validation.verify_google_id_token_signature",
                ) as verifier:
                    with self.assertRaises(services.GoogleOIDCTokenError):
                        services.validate_google_id_token(
                            id_token=token,
                            expected_nonce="nonce-value",
                            expected_client_id="client-id.apps.googleusercontent.com",
                            config=self.config,
                        )

                verifier.assert_not_called()

    def test_validate_id_token_rejects_disallowed_algorithm(self) -> None:
        """Reject tokens whose JWT header uses an unapproved algorithm.

        Args:
            self: The test case instance.
        """
        with mock.patch(
            "backend.accounts.services.token_validation.verify_google_id_token_signature",
        ) as verifier:
            with self.assertRaises(services.GoogleOIDCTokenError):
                services.validate_google_id_token(
                    id_token=fake_jwt(algorithm="HS256"),
                    expected_nonce="nonce-value",
                    expected_client_id="client-id.apps.googleusercontent.com",
                    config=self.config,
                )

        verifier.assert_not_called()

    def test_validate_id_token_rejects_signature_validation_failure(self) -> None:
        """Reject tokens when the Google Auth verifier rejects the signature.

        Args:
            self: The test case instance.
        """
        with mock.patch(
            "backend.accounts.services.token_validation.verify_google_id_token_signature",
            side_effect=services.GoogleOIDCTokenError("invalid signature"),
        ):
            with self.assertRaises(services.GoogleOIDCTokenError):
                services.validate_google_id_token(
                    id_token=fake_jwt(),
                    expected_nonce="nonce-value",
                    expected_client_id="client-id.apps.googleusercontent.com",
                    config=self.config,
                )


class GoogleOIDCSignatureTransportTests(SimpleTestCase):
    """Verify the bounded network boundary used for Google signing keys."""

    @mock.patch("google.auth.transport.requests.Request")
    @mock.patch("google.oauth2.id_token.verify_oauth2_token")
    def test_certificate_request_uses_exact_configured_timeout(
        self,
        verifier_mock: mock.Mock,
        request_class_mock: mock.Mock,
    ) -> None:
        """Apply the configured timeout to the certificate HTTP request.

        Args:
            self: The test case instance.
            verifier_mock: Mocked Google ID token verifier.
            request_class_mock: Mocked Google Auth request constructor.
        """
        transport_mock = mock.Mock()
        request_class_mock.return_value = transport_mock
        expected_claims = valid_claims(nonce="nonce-value")

        def verify_with_certificate_fetch(
            id_token: str,
            request: object,
            audience: str,
        ) -> dict[str, object]:
            """Exercise the request callable exactly as google-auth does.

            Args:
                id_token: Synthetic compact token supplied to google-auth.
                request: Bounded request callable supplied by the application.
                audience: Expected client identifier supplied by the application.

            Returns:
                Synthetic verified claims.
            """
            self.assertEqual(id_token, "synthetic-id-token")
            self.assertEqual(audience, "client-id.apps.googleusercontent.com")
            request(  # type: ignore[operator]
                "https://www.googleapis.com/oauth2/v1/certs",
                method="GET",
            )
            return expected_claims

        verifier_mock.side_effect = verify_with_certificate_fetch

        claims = services.verify_google_id_token_signature(
            id_token="synthetic-id-token",
            audience="client-id.apps.googleusercontent.com",
            timeout_seconds=7,
        )

        self.assertEqual(claims, expected_claims)
        transport_mock.assert_called_once_with(
            "https://www.googleapis.com/oauth2/v1/certs",
            method="GET",
            timeout=7,
        )

    @mock.patch("google.oauth2.id_token.verify_oauth2_token")
    def test_certificate_transport_error_becomes_generic_provider_failure(
        self,
        verifier_mock: mock.Mock,
    ) -> None:
        """Convert certificate network failures without exposing details.

        Args:
            self: The test case instance.
            verifier_mock: Mocked Google ID token verifier.
        """
        private_error = "private-network-endpoint"
        verifier_mock.side_effect = TransportError(private_error)

        with self.assertRaises(services.GoogleOIDCProviderError) as context:
            services.verify_google_id_token_signature(
                id_token="synthetic-sensitive-id-token",
                audience="client-id.apps.googleusercontent.com",
                timeout_seconds=5,
            )

        self.assertEqual(
            str(context.exception),
            "No se pudo verificar temporalmente el ID token de Google.",
        )
        self.assertNotIn(private_error, str(context.exception))
        self.assertNotIn("synthetic-sensitive-id-token", str(context.exception))
