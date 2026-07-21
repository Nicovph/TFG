"""Middleware that creates a trusted correlation identifier per HTTP request."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest
from django.http.response import HttpResponseBase

from .request_context import _bind_request_id, _reset_request_id


class RequestIdMiddleware:
    """Bind one server-generated UUID to each request execution context."""

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponseBase],
    ) -> None:
        """Store the next request handler in the Django middleware chain.

        Args:
            get_response: The next middleware or view callable.
        """
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        """Generate, bind and reliably clear a trusted request identifier.

        Args:
            request: The incoming Django HTTP request.

        Returns:
            The response produced by the remaining middleware and view chain.
        """
        request_id = uuid.uuid4()
        # Associates the request_id with the current context using ContextVar
        # and returns a token needed to restore it later.
        context_token = _bind_request_id(request_id)

        try:
            # Calls the next middleware or view.
            return self.get_response(request)
        finally:
            # It ensures that the previous context is always restored, even
            # if an exception occurs, preventing context "leaks" between requests.
            _reset_request_id(context_token)
