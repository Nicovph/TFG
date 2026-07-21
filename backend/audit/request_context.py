"""Request-scoped correlation context for structured security events."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token


# ContextVar allows for a variable whose value depends on the current
# execution context, rather than being a shared global variable
# (Each request (each "context") has its own request_id value).
_current_request_id: ContextVar[uuid.UUID | None] = ContextVar(
    "audit_current_request_id",
    default=None,
)


def get_current_request_id() -> uuid.UUID | None:
    """Return the server-generated identifier bound to the current request.

    Returns:
        The current request UUID, or None outside an HTTP request context.
    """
    return _current_request_id.get()


def _bind_request_id(request_id: uuid.UUID) -> Token[uuid.UUID | None]:
    """Bind a server-generated identifier to the current execution context.

    Args:
        request_id: The UUID generated at the trusted HTTP boundary.

    Returns:
        A context token that must be used to restore the previous value
        (normally None or a nested UUID, preventing a request's request_id
        from leaking into the next one).
    """
    return _current_request_id.set(request_id)


def _reset_request_id(token: Token[uuid.UUID | None]) -> None:
    """Restore the request correlation context to its previous value.

    Args:
        token: The token returned when the request identifier was bound.
    """
    _current_request_id.reset(token)
