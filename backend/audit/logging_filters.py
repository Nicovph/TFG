"""Logging filters that prevent sensitive request metadata from reaching handlers."""

import logging


def _remove_query_string(request_line: str) -> str:
    """Remove a query string from an HTTP request line without parsing its values.

    Args:
        request_line: Request line that may contain a query string.

    Returns:
        The request line with the query component removed.
    """
    query_start = request_line.find("?")
    if query_start < 0:
        return request_line

    protocol_start = request_line.find(" ", query_start)
    if protocol_start < 0:
        return request_line[:query_start]

    return request_line[:query_start] + request_line[protocol_start:]


class DjangoServerQueryStringFilter(logging.Filter):
    """Strip query strings from ``django.server`` records before any handler runs."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the request line stored in a Django server log record.

        Args:
            record: Log record emitted by Django's development server.

        Returns:
            Always ``True`` so the sanitized record continues to configured handlers.
        """
        # Strip query string when the request line is stored directly in msg.
        if isinstance(record.msg, str):
            record.msg = _remove_query_string(record.msg)

        # Strip query string from the first arg (common django.server format).
        if isinstance(record.args, tuple) and record.args:
            request_line = record.args[0]
            if isinstance(request_line, str):
                record.args = (
                    _remove_query_string(request_line),
                    *record.args[1:],
                )

        return True
