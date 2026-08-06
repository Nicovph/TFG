"""Narrow Groq adapter with strict output, bounded retries, and safe telemetry."""

from __future__ import annotations

import atexit
import json
import logging
import math
import random
import threading
import time
from collections.abc import Callable
from typing import Any, NoReturn

import groq
import httpx
from django.conf import settings
from pydantic import ValidationError

from backend.audit.request_context import get_current_request_id

from .contracts import LLMInterpretationOutput
from .prompts import ChatMessage


# This fixed origin prevents GROQ_BASE_URL or proxy environment variables from
# redirecting minimized user text and the backend-only API key.
GROQ_API_BASE_URL = "https://api.groq.com"

# The semaphore protects one Python process. Shared PostgreSQL quotas enforce
# application-wide request and token limits across processes and containers.
_PROVIDER_SEMAPHORE = threading.BoundedSemaphore(
    settings.LLM_MAX_CONCURRENT_PROVIDER_CALLS_PER_PROCESS
)
_CLIENT_LOCK = threading.Lock()
_shared_client: groq.Groq | None = None

# Module-level logger; __name__ enables the narrow hierarchical configuration
# in Django settings without exposing provider or user content.
logger = logging.getLogger(__name__)


class LlmProviderError(RuntimeError):
    """Base class for sanitized provider failures."""


class LlmProviderConfigurationError(LlmProviderError):
    """Indicate missing or invalid server-owned provider configuration."""


class LlmProviderTransientError(LlmProviderError):
    """Indicate a retryable provider failure after bounded attempts."""


class LlmProviderResponseError(LlmProviderError):
    """Indicate non-JSON, missing, or schema-invalid provider output."""


class LlmProviderRequestError(LlmProviderError):
    """Indicate a deterministic provider request or contract rejection."""


class LlmProviderBusyError(LlmProviderError):
    """Indicate local concurrency backpressure before any external call."""


def _provider_timeout(*, remaining_seconds: float | None = None) -> httpx.Timeout:
    """Build phase timeouts bounded by the remaining logical request budget.

    Args:
        remaining_seconds: Optional seconds left before the adapter deadline.

    Returns:
        An HTTPX timeout for connection, pool, write, and read inactivity.
    """
    read_timeout = float(settings.LLM_READ_TIMEOUT_SECONDS)
    connect_timeout = float(settings.LLM_CONNECT_TIMEOUT_SECONDS)

    if remaining_seconds is not None:
        # Avoids a timeout of 0 (which in httpx is interpreted as “no timeout”).
        positive_remaining = max(0.001, remaining_seconds)
        read_timeout = min(read_timeout, positive_remaining)
        connect_timeout = min(connect_timeout, positive_remaining)

    # Positional arg sets the default; keyword args override specific phases.
    # - connect: max time to establish the TCP/TLS socket.
    # - read: max time waiting for each response data chunk.
    # - write: max time waiting to send each request data chunk.
    # - pool: max time to acquire a connection from the pool.
    return httpx.Timeout(
        read_timeout,
        connect=connect_timeout,
        read=read_timeout,
        write=connect_timeout,
        pool=connect_timeout,
    )


def create_groq_client() -> groq.Groq:
    """Create a Groq client with an explicit trusted origin and HTTP policy.

    Returns:
        A configured synchronous Groq SDK client.

    Raises:
        LlmProviderConfigurationError: If no backend API key is configured.
    """
    if not settings.GROQ_API_KEY:
        raise LlmProviderConfigurationError(
            "Las credenciales de Groq no están disponibles."
        )

    # Disable implicit proxies and certificate overrides from the process
    # environment. Any future corporate proxy must be explicitly reviewed.
    http_client = httpx.Client(
        timeout=_provider_timeout(),
        limits=httpx.Limits(
            max_connections=(
                settings.LLM_MAX_CONCURRENT_PROVIDER_CALLS_PER_PROCESS
            ),
            # Inactive connections kept open for reuse.
            max_keepalive_connections=(
                settings.LLM_MAX_CONCURRENT_PROVIDER_CALLS_PER_PROCESS
            ),
        ),
        follow_redirects=False,
        trust_env=False,
    )

    try:
        return groq.Groq(
            api_key=settings.GROQ_API_KEY,
            base_url=GROQ_API_BASE_URL,
            http_client=http_client,
            max_retries=0,
        )
    except Exception:
        http_client.close()
        raise


def get_groq_client() -> groq.Groq:
    """Return one reusable, connection-pooled Groq client per process.

    Returns:
        The live process-local Groq client.

    Raises:
        LlmProviderConfigurationError: If backend credentials are unavailable.
        Exception: If the SDK client cannot be initialized.
    """
    # Causes the variable to be modified at the module level.
    global _shared_client

    # Lazy singleton: reuse the process-wide client when already initialized.
    if _shared_client is not None and not _shared_client.is_closed():
        return _shared_client

    # Double-checked locking avoids serializing normal requests (when the client
    # already exists) while ensuring that concurrent first requests create only
    # one shared connection pool.
    with _CLIENT_LOCK:
        if _shared_client is None or _shared_client.is_closed():
            _shared_client = create_groq_client()

        return _shared_client


def close_groq_client() -> None:
    """Close and detach the process-local Groq connection pool."""
    global _shared_client

    with _CLIENT_LOCK:
        client = _shared_client
        _shared_client = None

    if client is None:
        return

    try:
        client.close()
    except Exception:
        # Shutdown logging remains content-free and must not prevent process exit.
        logger.error(
            "llm_client_close provider=groq model=%s outcome=error "
            "error_type=provider_client_close",
            settings.GROQ_MODEL,
        )


# Normal interpreter shutdown closes persistent sockets deterministically (executes close_groq_client).
# A forced SIGKILL cannot run cleanup, but the operating system reclaims them.
atexit.register(close_groq_client)


def _response_format() -> dict[str, Any]:
    """Build the strict schema required for every allowed production model.

    Returns:
        Groq strict JSON Schema response configuration.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "pragmatic_interpretation",
            "strict": True,
            "schema": LLMInterpretationOutput.model_json_schema(),
        },
    }


def estimate_request_tokens(
    *,
    messages: list[ChatMessage],
    max_completion_tokens: int,
) -> int:
    """Estimate one padded token reservation for the complete Groq request.

    This dependency-free heuristic applies the common four-characters-per-token
    approximation to both messages and the strict response schema, then reserves
    the full completion budget. The result remains deliberately padded but must
    be calibrated against synthetic provider usage rather than described as
    exact tokenizer output.

    Args:
        messages: Provider messages held transiently in process memory.
        max_completion_tokens: Maximum server-configured completion budget.

    Returns:
        Approximate token units reserved for one provider attempt.

    Raises:
        ValueError: If the completion budget is not positive.
    """
    if max_completion_tokens < 1:
        raise ValueError(
            "El presupuesto máximo de tokens de salida debe ser positivo."
        )

    serialized_response_format = json.dumps(
        _response_format(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    request_character_count = (
        sum(len(item["content"]) for item in messages)
        + len(serialized_response_format)
    )
    message_overhead = len(messages) * 8

    return (
        math.ceil(request_character_count / 4)
        + message_overhead
        + max_completion_tokens
    )


def _completion_arguments(
    *,
    messages: list[ChatMessage],
) -> dict[str, Any]:
    """Build provider arguments exclusively from server-owned configuration.

    Args:
        messages: Guarded prompt messages prepared by the backend.

    Returns:
        Keyword arguments for the Groq chat completion call.
    """
    # Both allowed GPT-OSS models support strict schema decoding and hidden
    # reasoning. No fallback is permitted because it would weaken validation.
    return {
        "model": settings.GROQ_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_completion_tokens": settings.LLM_MAX_COMPLETION_TOKENS,
        "response_format": _response_format(),
        "reasoning_effort": "medium",
        "reasoning_format": "hidden",
        "stream": False,
    }


def _is_transient(exc: Exception) -> bool:
    """Classify only transport, capacity, and documented retryable failures.

    Args:
        exc: Exception raised by the Groq SDK.

    Returns:
        True for timeouts, connections, 408 (Request Timeout), 409 (Conflict),
            429, 498 (Flex Tier Capacity Exceeded), or 5xx.
    """
    if isinstance(
        exc,
        (groq.APITimeoutError, groq.APIConnectionError, groq.RateLimitError),
    ):
        return True

    if isinstance(exc, groq.APIStatusError):
        return exc.status_code in {408, 409, 429, 498} or exc.status_code >= 500

    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    """Read a finite positive Retry-After value without logging headers.

    Args:
        exc: Transient provider exception.

    Returns:
        Provider-requested delay in seconds, or None when absent or invalid.
    """
    if not isinstance(exc, groq.APIStatusError):
        return None

    raw_retry_after = exc.response.headers.get("retry-after", "")

    try:
        retry_after = float(raw_retry_after)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(retry_after) or retry_after <= 0:
        return None

    return retry_after


def _retry_delay_seconds(
    *,
    exc: Exception,
    attempt_index: int,
    jitter_source: Callable[[float, float], float],
) -> float:
    """Compute capped exponential backoff with full jitter.

    Args:
        exc: Transient provider exception.
        attempt_index: Zero-based failed attempt index.
        jitter_source: Injectable uniform random source for deterministic tests.

    Returns:
        A delay that respects a short provider Retry-After value.
    """
    maximum_delay = float(settings.LLM_MAX_RETRY_DELAY_SECONDS)
    exponential_cap = min(
        maximum_delay,
        (settings.LLM_RETRY_BASE_MILLISECONDS / 1000)
        * (2 ** attempt_index),
    )
    jitter = min(
        exponential_cap,
        max(0.0, jitter_source(0.0, exponential_cap)),
    )
    retry_after = _retry_after_seconds(exc)
    return max(jitter, retry_after or 0.0)


def _accounted_usage(
    *,
    response: object | None,
    estimated_tokens: int,
    attempt_count: int,
) -> tuple[int, str]:
    """Account conservatively for retries without reading provider content.

    Args:
        response: Optional Groq SDK completion response.
        estimated_tokens: Pre-call conservative token estimate per attempt.
        attempt_count: Number of external calls made for the logical request.

    Returns:
        Accounted token units and a closed source label.
    """
    usage = getattr(response, "usage", None)
    total_tokens = getattr(usage, "total_tokens", None)
    failed_attempts = max(0, attempt_count - 1)

    if isinstance(total_tokens, int) and total_tokens >= 0:
        accounted_tokens = total_tokens + failed_attempts * estimated_tokens
        source = "provider" if failed_attempts == 0 else "provider_plus_estimate"
        return accounted_tokens, source

    return max(0, attempt_count) * estimated_tokens, "estimate"


def _log_result(
    *,
    outcome: str,
    error_type: str,
    latency_ms: int,
    accounted_tokens: int,
    usage_source: str,
    attempt_count: int,
) -> None:
    """Log only closed operational metadata at an actionable severity.

    Args:
        outcome: Closed success or error label.
        error_type: Closed sanitized error category or none.
        latency_ms: Total adapter latency in milliseconds.
        accounted_tokens: Aggregate provider or estimated token units.
        usage_source: Closed provider, estimate, or mixed source label.
        attempt_count: Number of calls sent to Groq.
    """
    log_method = logger.info

    if outcome == "error":
        if error_type in {
            "provider_configuration",
            "provider_client_configuration",
            "provider_unexpected",
        }:
            log_method = logger.error
        else:
            log_method = logger.warning

    log_method(
        "llm_request provider=groq model=%s outcome=%s error_type=%s "
        "latency_ms=%d accounted_tokens=%d usage_source=%s "
        "attempt_count=%d request_id=%s",
        settings.GROQ_MODEL,
        outcome,
        error_type,
        latency_ms,
        accounted_tokens,
        usage_source,
        attempt_count,
        get_current_request_id() or "none",
    )


def _log_accounted_result(
    *,
    outcome: str,
    error_type: str,
    started_at: float,
    clock: Callable[[], float],
    response: object | None,
    estimated_tokens: int,
    attempt_count: int,
) -> None:
    """Calculate content-free accounting and emit one operational result.

    Args:
        outcome: Closed success or error label.
        error_type: Closed sanitized error category or none.
        started_at: Monotonic adapter start time.
        clock: Monotonic clock used by the active request.
        response: Optional provider response used only for aggregate usage.
        estimated_tokens: Conservative token estimate for one attempt.
        attempt_count: Number of calls sent to Groq.
    """
    accounted_tokens, usage_source = _accounted_usage(
        response=response,
        estimated_tokens=estimated_tokens,
        attempt_count=attempt_count,
    )
    _log_result(
        outcome=outcome,
        error_type=error_type,
        latency_ms=int((clock() - started_at) * 1000),
        accounted_tokens=accounted_tokens,
        usage_source=usage_source,
        attempt_count=attempt_count,
    )


# NoReturn is used because the method always raises an exception.
def _raise_transient_failure(
    *,
    message: str,
    error_type: str,
    started_at: float,
    clock: Callable[[], float],
    response: object | None,
    estimated_tokens: int,
    attempt_count: int,
    cause: Exception | None = None,
) -> NoReturn:
    """Log and raise one sanitized terminal transient failure.

    Args:
        message: Sanitized Spanish exception message.
        error_type: Closed operational error category.
        started_at: Monotonic adapter start time.
        clock: Monotonic clock used by the active request.
        response: Optional provider response used only for aggregate usage.
        estimated_tokens: Conservative token estimate for one attempt.
        attempt_count: Number of calls sent to Groq.
        cause: Optional internal exception preserved only in the traceback.

    Raises:
        LlmProviderTransientError: Always, after recording safe telemetry.
    """
    _log_accounted_result(
        outcome="error",
        error_type=error_type,
        started_at=started_at,
        clock=clock,
        response=response,
        estimated_tokens=estimated_tokens,
        attempt_count=attempt_count,
    )
    error = LlmProviderTransientError(message)

    if cause is not None:
        raise error from cause

    raise error


def _non_transient_failure(
    exc: groq.APIError,
) -> tuple[str, type[LlmProviderError], str]:
    """Map deterministic SDK failures to closed internal categories.

    Args:
        exc: Non-transient Groq SDK exception.

    Returns:
        Log category, sanitized exception class, and sanitized message.
    """
    status_code = (
        exc.status_code if isinstance(exc, groq.APIStatusError) else None
    )

    if status_code in {400, 401, 403, 404}:
        return (
            "provider_configuration",
            LlmProviderConfigurationError,
            "La configuración del proveedor no es válida.",
        )

    if status_code in {413, 422}:
        return (
            "provider_request",
            LlmProviderRequestError,
            "El proveedor rechazó el contrato de la solicitud.",
        )

    return (
        "provider_non_transient",
        LlmProviderError,
        "El proveedor rechazó la solicitud.",
    )


# Factories, clocks, sleepers, and jitter are injectable so tests never use
# real network traffic or nondeterministic timing.
def request_interpretation(
    *,
    messages: list[ChatMessage],
    approximate_tokens: int,
    attempt_reserver: Callable[[], None],
    client_factory: Callable[[], groq.Groq] = get_groq_client,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    jitter_source: Callable[[float, float], float] = random.uniform,
) -> LLMInterpretationOutput:
    """Call Groq within a logical deadline and validate untrusted output.

    Args:
        messages: Backend-built guarded prompt messages.
        approximate_tokens: Content-free token estimate for one provider attempt.
        attempt_reserver: Callback reserving application quotas immediately
            before every potential external call.
        client_factory: Injectable process-local Groq client provider.
        sleeper: Injectable bounded backoff function.
        clock: Injectable monotonic clock used for the logical deadline.
        jitter_source: Injectable full-jitter random source.

    Returns:
        Strictly validated Pydantic output.

    Raises:
        LlmProviderBusyError: If local concurrency capacity is exhausted.
        LlmProviderConfigurationError: If credentials or configuration are invalid.
        LlmProviderTransientError: If transient failures exhaust the budget.
        LlmProviderResponseError: If output is missing, non-JSON, or schema-invalid.
        LlmProviderRequestError: If the provider rejects the request contract.
        LlmProviderError: If another non-transient provider error occurs.
    """
    # A non-blocking acquire returns False instead of waiting when no permit is
    # available, so local concurrency exhaustion fails fast.
    if not _PROVIDER_SEMAPHORE.acquire(blocking=False):
        # This operational record is sufficient for local saturation. Creating
        # one persistent audit row per affected user would duplicate telemetry
        # and allow a provider outage to amplify database writes.
        _log_result(
            outcome="error",
            error_type="provider_local_busy",
            latency_ms=0,
            accounted_tokens=0,
            usage_source="estimate",
            attempt_count=0,
        )
        raise LlmProviderBusyError(
            "Se ha agotado la capacidad de concurrencia local del proveedor."
        )

    started_at = clock()
    deadline = started_at + settings.LLM_TOTAL_TIMEOUT_SECONDS
    response: object | None = None
    attempt_count = 0

    try:
        try:
            client = client_factory()
        except LlmProviderConfigurationError:
            _log_accounted_result(
                outcome="error",
                error_type="provider_configuration",
                started_at=started_at,
                clock=clock,
                response=None,
                estimated_tokens=approximate_tokens,
                attempt_count=0,
            )
            raise
        except Exception as exc:
            _log_accounted_result(
                outcome="error",
                error_type="provider_client_configuration",
                started_at=started_at,
                clock=clock,
                response=None,
                estimated_tokens=approximate_tokens,
                attempt_count=0,
            )
            raise LlmProviderConfigurationError(
                "No se pudo inicializar el cliente del proveedor."
            ) from exc

        for attempt_index in range(settings.LLM_MAX_ATTEMPTS):
            remaining_seconds = deadline - clock()

            if remaining_seconds <= 0:
                _raise_transient_failure(
                    message=(
                        "Se agotó el tiempo total permitido para el proveedor."
                    ),
                    error_type="provider_total_timeout",
                    started_at=started_at,
                    clock=clock,
                    response=response,
                    estimated_tokens=approximate_tokens,
                    attempt_count=attempt_count,
                )

            try:
                # Capacity is reserved only after local concurrency and client
                # initialization succeed, but before Groq can consume tokens.
                attempt_reserver()
            except Exception:
                # Preserve the quota or configuration exception so the service
                # and view can retain their stable error classification.
                _log_accounted_result(
                    outcome="error",
                    error_type="provider_attempt_reservation_failed",
                    started_at=started_at,
                    clock=clock,
                    response=response,
                    estimated_tokens=approximate_tokens,
                    attempt_count=attempt_count,
                )
                raise

            # Database quota reservation also consumes part of the logical
            # deadline, so the HTTP timeout must use a freshly computed budget.
            remaining_seconds = deadline - clock()

            if remaining_seconds <= 0:
                _raise_transient_failure(
                    message=(
                        "Se agotó el tiempo total permitido antes de llamar "
                        "al proveedor."
                    ),
                    error_type="provider_total_timeout",
                    started_at=started_at,
                    clock=clock,
                    response=response,
                    estimated_tokens=approximate_tokens,
                    attempt_count=attempt_count,
                )

            attempt_count += 1

            try:
                response = client.chat.completions.create(
                    **_completion_arguments(messages=messages),
                    timeout=_provider_timeout(
                        remaining_seconds=remaining_seconds,
                    ),
                )
                break
            except Exception as exc:
                if not isinstance(exc, groq.APIError):
                    _log_accounted_result(
                        outcome="error",
                        error_type="provider_unexpected",
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                    )
                    raise LlmProviderError(
                        "Se produjo un fallo inesperado en el adaptador "
                        "del proveedor."
                    ) from exc

                if not _is_transient(exc):
                    error_type, exception_type, message = (
                        _non_transient_failure(exc)
                    )
                    _log_accounted_result(
                        outcome="error",
                        error_type=error_type,
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                    )
                    raise exception_type(message) from exc

                if attempt_index + 1 >= settings.LLM_MAX_ATTEMPTS:
                    _raise_transient_failure(
                        message=(
                            "Se agotaron los intentos por errores transitorios "
                            "del proveedor."
                        ),
                        error_type="provider_transient",
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                        cause=exc,
                    )

                retry_after = _retry_after_seconds(exc)

                if (
                    retry_after is not None
                    and retry_after > settings.LLM_MAX_RETRY_DELAY_SECONDS
                ):
                    _raise_transient_failure(
                        message=(
                            "El proveedor no dispone de capacidad dentro del "
                            "plazo de reintento permitido."
                        ),
                        error_type="provider_retry_after_exceeded",
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                        cause=exc,
                    )

                delay = _retry_delay_seconds(
                    exc=exc,
                    attempt_index=attempt_index,
                    jitter_source=jitter_source,
                )
                remaining_seconds = deadline - clock()

                if delay >= remaining_seconds:
                    _raise_transient_failure(
                        message=(
                            "No queda tiempo suficiente para reintentar "
                            "la solicitud."
                        ),
                        error_type="provider_total_timeout",
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                        cause=exc,
                    )

                sleeper(delay)

                if deadline - clock() <= 0:
                    _raise_transient_failure(
                        message=(
                            "Se agotó el tiempo total permitido durante "
                            "el reintento."
                        ),
                        error_type="provider_total_timeout",
                        started_at=started_at,
                        clock=clock,
                        response=response,
                        estimated_tokens=approximate_tokens,
                        attempt_count=attempt_count,
                        cause=exc,
                    )

        try:
            content = response.choices[0].message.content if response else None
        except (AttributeError, IndexError, TypeError):
            content = None

        if not isinstance(content, str) or not content.strip():
            raise LlmProviderResponseError(
                "Falta el contenido de la respuesta del proveedor."
            )

        try:
            validated = LLMInterpretationOutput.model_validate_json(content)
        except ValidationError as exc:
            raise LlmProviderResponseError(
                "La respuesta del proveedor no superó la validación del esquema."
            ) from exc

        _log_accounted_result(
            outcome="success",
            error_type="none",
            started_at=started_at,
            clock=clock,
            response=response,
            estimated_tokens=approximate_tokens,
            attempt_count=attempt_count,
        )
        return validated
    except LlmProviderResponseError:
        _log_accounted_result(
            outcome="error",
            error_type="invalid_response",
            started_at=started_at,
            clock=clock,
            response=response,
            estimated_tokens=approximate_tokens,
            attempt_count=attempt_count,
        )
        raise
    finally:
        _PROVIDER_SEMAPHORE.release()
