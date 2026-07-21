"""Tests for trusted request correlation middleware behavior."""

import uuid
from collections.abc import Iterator

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TestCase

from backend.accounts.models import CustomUser

from ..middleware import RequestIdMiddleware
from ..models import SecurityEvent, SecurityEventType
from ..request_context import get_current_request_id


class RequestIdMiddlewareTests(TestCase):
    """Verify trusted request IDs are correlated and isolated per request."""

    def setUp(self) -> None:
        """Create an actor used by request-scoped audit events.

        Args:
            self: The test case instance.
        """
        # Allows to create simulated HttpRequest objects.
        self.factory = RequestFactory()
        self.actor = CustomUser.objects.create_user(
            google_subject="audit-request-context-subject",
        )

    def test_middleware_uses_one_server_id_for_all_request_events(self) -> None:
        """Ignore client IDs and correlate every event created by one request.

        Args:
            self: The test case instance.
        """
        client_supplied_id = uuid.uuid4()
        observed_request_ids: list[uuid.UUID | None] = []

        def create_audit_events(request: HttpRequest) -> HttpResponse:
            """Create two events inside the active request context.

            Args:
                request: The request processed by the middleware.

            Returns:
                An empty successful response.
            """
            observed_request_ids.append(get_current_request_id())
            SecurityEvent.objects.record(
                event_type=SecurityEventType.LOGIN_SUCCEEDED,
                actor=self.actor,
            )
            SecurityEvent.objects.record(
                event_type=SecurityEventType.LOGOUT,
                actor=self.actor,
            )
            return HttpResponse(status=204)

        # Request ID supplied by the client.
        request = self.factory.get(
            "/audit-request-context/",
            HTTP_X_REQUEST_ID=str(client_supplied_id),
        )
        response = RequestIdMiddleware(create_audit_events)(request)

        events = list(SecurityEvent.objects.order_by("event_type"))
        persisted_request_ids = {event.request_id for event in events}

        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(persisted_request_ids), 1)
        server_request_id = persisted_request_ids.pop()
        self.assertIsInstance(server_request_id, uuid.UUID)
        self.assertNotEqual(server_request_id, client_supplied_id)
        self.assertEqual(
            observed_request_ids,
            [server_request_id],
        )
        self.assertIsNone(get_current_request_id())

    def test_middleware_clears_request_id_when_processing_raises(self) -> None:
        """Prevent a failed request from leaking its ID into later work.

        Args:
            self: The test case instance.
        """
        def raise_processing_error(request: HttpRequest) -> HttpResponse:
            """Raise after confirming that the request context is active.

            Args:
                request: The request processed by the middleware.

            Raises:
                RuntimeError: Always, to exercise context cleanup.

            Returns:
                This function does not return.
            """
            self.assertIsInstance(get_current_request_id(), uuid.UUID)
            raise RuntimeError("request processing failed")

        middleware = RequestIdMiddleware(raise_processing_error)
        request = self.factory.get("/audit-request-error/")

        with self.assertRaisesMessage(RuntimeError, "request processing failed"):
            middleware(request)

        self.assertIsNone(get_current_request_id())

    def test_middleware_generates_distinct_ids_for_separate_requests(self) -> None:
        """Prevent unrelated requests from sharing an audit correlation ID.

        Args:
            self: The test case instance.
        """
        observed_request_ids: list[uuid.UUID] = []

        def create_audit_event(request: HttpRequest) -> HttpResponse:
            """Record one event and capture its request-scoped identifier.

            Args:
                request: The request processed by the middleware.

            Returns:
                An empty successful response.
            """
            request_id = get_current_request_id()
            if request_id is None:
                self.fail("The request ID must be bound while processing.")
            observed_request_ids.append(request_id)
            SecurityEvent.objects.record(
                event_type=SecurityEventType.LOGIN_SUCCEEDED,
                actor=self.actor,
            )
            return HttpResponse(status=204)

        middleware = RequestIdMiddleware(create_audit_event)

        middleware(self.factory.get("/audit-request-one/"))
        middleware(self.factory.get("/audit-request-two/"))

        persisted_request_ids = {
            event.request_id
            for event in SecurityEvent.objects.all()
        }
        self.assertEqual(len(observed_request_ids), 2)
        # The * unpacks the list to compare the two ids.
        self.assertNotEqual(*observed_request_ids)
        # set is used, because persisted_request_ids is a set.
        self.assertEqual(persisted_request_ids, set(observed_request_ids))
        self.assertIsNone(get_current_request_id())

    def test_nested_middleware_restores_previous_request_context(self) -> None:
        """Restore an outer request ID after nested middleware processing.

        Args:
            self: The test case instance.
        """
        observed_inner_request_ids: list[uuid.UUID] = []
        observed_outer_request_ids: list[uuid.UUID] = []

        def process_inner_request(request: HttpRequest) -> HttpResponse:
            """Capture the nested request correlation identifier.

            Args:
                request: The nested request processed by the middleware.

            Returns:
                An empty successful response.
            """
            request_id = get_current_request_id()
            if request_id is None:
                self.fail("El ID de la solicitud anidada debe estar vinculado durante el procesamiento.")
            observed_inner_request_ids.append(request_id)
            return HttpResponse(status=204)

        inner_middleware = RequestIdMiddleware(process_inner_request)

        def process_outer_request(request: HttpRequest) -> HttpResponse:
            """Run nested middleware and verify restoration of the outer ID.

            Args:
                request: The outer request processed by the middleware.

            Returns:
                An empty successful response.
            """
            # Capture the external request ID before executing the internal middleware.
            outer_request_id = get_current_request_id()
            if outer_request_id is None:
                self.fail("El ID de solicitud externo debe estar vinculado durante el procesamiento.")
            observed_outer_request_ids.append(outer_request_id)
            # Executes the internal middleware, simulating nesting.
            inner_middleware(self.factory.get("/audit-request-inner/"))
            # It must be the same as the outer request id, because is the value to restore from the inner middleware.
            restored_request_id = get_current_request_id()
            if restored_request_id is None:
                self.fail("El ID de solicitud externo debe restaurarse tras el anidamiento.")
            observed_outer_request_ids.append(restored_request_id)
            return HttpResponse(status=204)

        outer_middleware = RequestIdMiddleware(process_outer_request)

        outer_middleware(self.factory.get("/audit-request-outer/"))

        self.assertEqual(len(observed_inner_request_ids), 1)
        self.assertEqual(len(observed_outer_request_ids), 2)
        self.assertEqual(*observed_outer_request_ids)
        self.assertNotEqual(
            observed_outer_request_ids[0],
            observed_inner_request_ids[0],
        )
        self.assertIsNone(get_current_request_id())

    def test_middleware_clears_context_before_streaming_content_is_consumed(
        self,
    ) -> None:
        """Document that request context ends before streaming iteration.

        Args:
            self: The test case instance.
        """
        observed_during_stream: list[uuid.UUID | None] = []

        def content() -> Iterator[bytes]:
            """Yield content after capturing the current correlation context.
                Generator that simulates the response content.    

            Returns:
                An iterator that yields a single response chunk.
            """
            # Capture the request_id at the moment Django iterates over the 
            # stream (not during response creation).
            observed_during_stream.append(get_current_request_id())
            yield b"chunk"

        def create_streaming_response(
            request: HttpRequest,
        ) -> StreamingHttpResponse:
            """Return a streaming response while the request context is active.

            Args:
                request: The request processed by the middleware.

            Returns:
                A response with a single streaming content chunk.
            """
            self.assertIsInstance(get_current_request_id(), uuid.UUID)
            return StreamingHttpResponse(content())

        middleware = RequestIdMiddleware(create_streaming_response)

        response = middleware(self.factory.get("/audit-request-streaming/"))

        self.assertIsInstance(response, StreamingHttpResponse)
        self.assertTrue(response.streaming)
        self.assertIsNone(get_current_request_id())
        self.assertEqual(b"".join(response.streaming_content), b"chunk")
        # Confirm that after processing the middleware (but before consuming 
        # the stream), the context is already cleared (None).
        self.assertEqual(observed_during_stream, [None])
