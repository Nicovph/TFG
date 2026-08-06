"""Transient input minimisation and output identifier-candidate detection."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class IdentifierCategory(StrEnum):
    """Define the closed identifier-candidate categories used in memory."""

    EMAIL = "email"
    URL = "url"
    IBAN_CANDIDATE = "iban_candidate"
    SPANISH_IDENTITY_CANDIDATE = "spanish_identity_candidate"
    PHONE_CANDIDATE = "phone_candidate"
    SOCIAL_HANDLE = "social_handle"
    IP_ADDRESS_CANDIDATE = "ip_address_candidate"
    LONG_NUMERIC_CANDIDATE = "long_numeric_candidate"


@dataclass(frozen=True, slots=True)
class MinimizedMessage:
    """Hold transient minimized text and detected identifier categories."""

    text: str
    detected_categories: frozenset[IdentifierCategory]


@dataclass(frozen=True, slots=True)
class _RedactionRule:
    """Associate one candidate pattern with its closed placeholder category."""

    category: IdentifierCategory
    placeholder_label: str
    pattern: re.Pattern[str]


# This is a privacy-oriented candidate detector, not a complete RFC validator.
# Unicode letters are accepted in domain labels and top-level domains.
_EMAIL_CANDIDATE = re.compile(
    r"(?<![\w.+-])"
    r"[\w.!#$%&'*+/=?^`{|}~-]+@"
    r"(?:[\w-]+\.)+"
    r"(?:xn--[a-z0-9-]{2,}|[^\W\d_]{2,})"
    r"(?![\w-])",
    re.IGNORECASE,
)

# In Python regexes, \b is the boundary between a word and non-word character
# or a string edge. The replacement callback preserves trailing punctuation.
_URL_CANDIDATE = re.compile(
    r"\b(?:https?://|www\.)[^\s<>]+",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"

# The current project scope intentionally covers Spanish IBAN candidates only.
# Candidate detection is based on shape and does not require a valid checksum.
_SPANISH_IBAN_CANDIDATE = re.compile(
    r"\bES\d{2}(?:[ -]?\d{4}){5}\b",
    re.IGNORECASE,
)
_SPANISH_IDENTITY_CANDIDATE = re.compile(
    r"\b(?:\d{8}[ -]?[A-Z]|[XYZ][ -]?\d{7}[ -]?[A-Z])\b",
    re.IGNORECASE,
)
_SPANISH_PHONE_CANDIDATE = re.compile(
    r"(?<!\d)(?:(?:\+|00)34[ -]?)?[6789](?:[ -]?\d){8}(?![ -]?\d)"
)
_SOCIAL_HANDLE_CANDIDATE = re.compile(
    r"(?<!\w)@[A-Za-z0-9_]{2,32}\b"
)

# Ten or more digits are treated as a generic identifier candidate. This rule
# deliberately avoids claiming that the value is a validated payment card.
_LONG_NUMERIC_CANDIDATE = re.compile(
    r"(?<!\d)(?:\d[ -]?){9,}\d(?!\d)"
)

_IPV4_CANDIDATE = re.compile(
    r"(?<![\w.])"
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"(?!(?:\.\d)|\w)"
)

# IPv6 extraction from free text is intentionally broad; ipaddress performs
# the semantic validation. The pattern also finds bracketed and scoped forms.
_IPV6_CANDIDATE = re.compile(
    r"(?<![\w:])"
    r"(?:\[[0-9A-Za-z_.:%-]+\]|[0-9A-Za-z_.%+-]*:[0-9A-Za-z_.:%+-]+)"
    r"(?![\w:])"
)
_TRAILING_IP_PUNCTUATION = ".,;!?"

_STANDARD_RULES: tuple[_RedactionRule, ...] = (
    _RedactionRule(
        category=IdentifierCategory.EMAIL,
        placeholder_label="EMAIL",
        pattern=_EMAIL_CANDIDATE,
    ),
    _RedactionRule(
        category=IdentifierCategory.IBAN_CANDIDATE,
        placeholder_label="IBAN",
        pattern=_SPANISH_IBAN_CANDIDATE,
    ),
    _RedactionRule(
        category=IdentifierCategory.SPANISH_IDENTITY_CANDIDATE,
        placeholder_label="DOCUMENTO",
        pattern=_SPANISH_IDENTITY_CANDIDATE,
    ),
    _RedactionRule(
        category=IdentifierCategory.PHONE_CANDIDATE,
        placeholder_label="TELEFONO",
        pattern=_SPANISH_PHONE_CANDIDATE,
    ),
    _RedactionRule(
        category=IdentifierCategory.SOCIAL_HANDLE,
        placeholder_label="USUARIO",
        pattern=_SOCIAL_HANDLE_CANDIDATE,
    ),
    _RedactionRule(
        category=IdentifierCategory.LONG_NUMERIC_CANDIDATE,
        placeholder_label="NUMERO_LARGO",
        pattern=_LONG_NUMERIC_CANDIDATE,
    ),
)


def normalize_message_text(message: str) -> str:
    """Normalize compatibility-equivalent Unicode before local inspection.

    Args:
        message: Validated text held only in process memory.

    Returns:
        The NFKC-normalized Unicode string.
    """
    return unicodedata.normalize("NFKC", message)


def _placeholder_for(
    *,
    category: IdentifierCategory,
    placeholder_label: str,
    candidate_key: str,
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> str:
    """Return a stable per-message placeholder for one distinct candidate.

    Args:
        category: Closed category assigned by the matching rule.
        placeholder_label: Non-sensitive label rendered in the minimized text.
        candidate_key: Transient normalized value used only during this call.
        placeholder_registry: Per-message mappings that are never returned.

    Returns:
        A numbered placeholder, reused for repeated identical candidates.
    """
    # It contains the placeholders already generated for that specific category in
    # the current message, or an empty dictionary if none have been generated yet.
    category_registry = placeholder_registry.setdefault(category, {})
    # It checks whether `candidate_key` is already registered, in order to reuse
    # the same placeholder if it is.
    existing_placeholder = category_registry.get(candidate_key)

    if existing_placeholder is not None:
        return existing_placeholder

    placeholder = f"[{placeholder_label}_{len(category_registry) + 1}]"
    category_registry[candidate_key] = placeholder
    return placeholder


def _replace_pattern_candidates(
    *,
    message: str,
    rule: _RedactionRule,
    categories: set[IdentifierCategory],
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> str:
    """Replace every candidate found by one standard redaction rule.

    Args:
        message: Text being minimized in process memory.
        rule: Closed category, label, and candidate pattern to apply.
        categories: Mutable set receiving the detected category.
        placeholder_registry: Per-message mapping for stable numbering.

    Returns:
        Text with matching candidates replaced by numbered placeholders.
    """

    def replace_candidate(match: re.Match[str]) -> str:
        """Replace one match without retaining it beyond the current call.

        Args:
            match: Candidate substring detected by the rule.

        Returns:
            The stable numbered placeholder for this candidate.
        """
        categories.add(rule.category)
        return _placeholder_for(
            category=rule.category,
            placeholder_label=rule.placeholder_label,
            candidate_key=match.group(0).casefold(),
            placeholder_registry=placeholder_registry,
        )

    return rule.pattern.sub(replace_candidate, message)


def _replace_url_candidates(
    *,
    message: str,
    categories: set[IdentifierCategory],
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> str:
    """Replace URL candidates while preserving sentence punctuation.

    Args:
        message: Text being minimized in process memory.
        categories: Mutable set receiving the URL category.
        placeholder_registry: Per-message mapping for stable numbering.

    Returns:
        Text with URL candidates replaced and trailing punctuation preserved.
    """

    def replace_candidate(match: re.Match[str]) -> str:
        """Separate one URL candidate from punctuation that follows it.

        Args:
            match: Candidate URL and any punctuation consumed by the pattern.

        Returns:
            A numbered URL placeholder followed by preserved punctuation.
        """
        matched = match.group(0)
        url = matched.rstrip(_TRAILING_URL_PUNCTUATION)
        trailing = matched[len(url):]

        if not url:
            return matched

        categories.add(IdentifierCategory.URL)
        placeholder = _placeholder_for(
            category=IdentifierCategory.URL,
            placeholder_label="URL",
            candidate_key=url.casefold(),
            placeholder_registry=placeholder_registry,
        )
        return f"{placeholder}{trailing}"

    return _URL_CANDIDATE.sub(replace_candidate, message)


def _canonical_ipv4_candidate(candidate: str) -> str | None:
    """Validate and canonicalize one dotted-decimal IPv4 candidate.

    Args:
        candidate: Candidate extracted from free text.

    Returns:
        A canonical address, including conservative leading-zero forms, or None.
    """
    try:
        return str(ipaddress.IPv4Address(candidate))
    except ipaddress.AddressValueError:
        octets = candidate.split(".")

        if (
            len(octets) == 4
            and all(octet.isdecimal() for octet in octets)
            and all(0 <= int(octet, 10) <= 255 for octet in octets)
        ):
            # Falls back to a permissive decimal check that accepts and normalizes
            # leading zeros (e.g. 192.168.001.010).
            return ".".join(str(int(octet, 10)) for octet in octets)

        return None


def _canonical_ipv6_candidate(candidate: str) -> str | None:
    """Validate and canonicalize one extracted IPv6 candidate.

    Args:
        candidate: Candidate that may include brackets or trailing punctuation.

    Returns:
        The canonical IPv6 form, or None when the candidate is not an address.
    """
    without_punctuation = candidate.rstrip(_TRAILING_IP_PUNCTUATION)
    unbracketed = without_punctuation

    if unbracketed.startswith("[") and unbracketed.endswith("]"):
        unbracketed = unbracketed[1:-1]

    try:
        address = ipaddress.ip_address(unbracketed)
    except ValueError:
        return None

    if address.version != 6:
        return None

    return str(address)


def _replace_ipv6_candidates(
    *,
    message: str,
    categories: set[IdentifierCategory],
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> str:
    """Replace semantically valid IPv6 candidates in free text.

    Args:
        message: Text being minimized in process memory.
        categories: Mutable set receiving the IP candidate category.
        placeholder_registry: Per-message mapping for stable numbering.

    Returns:
        Text with valid IPv6 candidates replaced by numbered placeholders.
    """

    def replace_candidate(match: re.Match[str]) -> str:
        """Validate one broad IPv6 candidate before replacing it.

        Args:
            match: Candidate substring extracted from free text.

        Returns:
            A numbered placeholder for IPv6, otherwise the original text.
        """
        matched = match.group(0)
        canonical = _canonical_ipv6_candidate(matched)

        if canonical is None:
            return matched

        trailing = matched[len(matched.rstrip(_TRAILING_IP_PUNCTUATION)):]
        categories.add(IdentifierCategory.IP_ADDRESS_CANDIDATE)
        placeholder = _placeholder_for(
            category=IdentifierCategory.IP_ADDRESS_CANDIDATE,
            placeholder_label="IP",
            candidate_key=canonical,
            placeholder_registry=placeholder_registry,
        )
        return f"{placeholder}{trailing}"

    return _IPV6_CANDIDATE.sub(replace_candidate, message)


def _replace_ipv4_candidates(
    *,
    message: str,
    categories: set[IdentifierCategory],
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> str:
    """Replace valid or conservatively recognized IPv4 candidates.

    Args:
        message: Text being minimized in process memory.
        categories: Mutable set receiving the IP candidate category.
        placeholder_registry: Per-message mapping for stable numbering.

    Returns:
        Text with recognized IPv4 candidates replaced by placeholders.
    """

    def replace_candidate(match: re.Match[str]) -> str:
        """Validate one dotted-decimal candidate before replacing it.

        Args:
            match: Candidate IPv4 substring.

        Returns:
            A numbered IP placeholder or the original candidate.
        """
        candidate = match.group(0)
        canonical = _canonical_ipv4_candidate(candidate)

        if canonical is None:
            return candidate

        categories.add(IdentifierCategory.IP_ADDRESS_CANDIDATE)
        return _placeholder_for(
            category=IdentifierCategory.IP_ADDRESS_CANDIDATE,
            placeholder_label="IP",
            candidate_key=canonical,
            placeholder_registry=placeholder_registry,
        )

    return _IPV4_CANDIDATE.sub(replace_candidate, message)


def _contains_valid_ip_candidate(message: str) -> bool:
    """Report whether free text contains a semantically valid IP candidate.

    Args:
        message: NFKC-normalized text held only in process memory.

    Returns:
        True when an IPv4 or IPv6 candidate passes local validation.
    """
    if any(
        _canonical_ipv6_candidate(match.group(0)) is not None
        for match in _IPV6_CANDIDATE.finditer(message)
    ):
        return True

    return any(
        _canonical_ipv4_candidate(match.group(0)) is not None
        for match in _IPV4_CANDIDATE.finditer(message)
    )


def _minimize_message_with_registry(
    *,
    message: str,
    placeholder_registry: dict[IdentifierCategory, dict[str, str]],
) -> MinimizedMessage:
    """Minimize one text using a request-scoped placeholder registry.

    Args:
        message: Validated user message held only in process memory.
        placeholder_registry: Transient mappings shared by one logical request.

    Returns:
        Transient minimized text and the candidate categories that were found.
    """
    minimized = normalize_message_text(message)
    categories: set[IdentifierCategory] = set()

    minimized = _replace_url_candidates(
        message=minimized,
        categories=categories,
        placeholder_registry=placeholder_registry,
    )
    minimized = _replace_ipv6_candidates(
        message=minimized,
        categories=categories,
        placeholder_registry=placeholder_registry,
    )
    minimized = _replace_ipv4_candidates(
        message=minimized,
        categories=categories,
        placeholder_registry=placeholder_registry,
    )

    for rule in _STANDARD_RULES:
        minimized = _replace_pattern_candidates(
            message=minimized,
            rule=rule,
            categories=categories,
            placeholder_registry=placeholder_registry,
        )

    return MinimizedMessage(
        text=minimized,
        detected_categories=frozenset(categories),
    )


def minimize_message_for_provider(message: str) -> MinimizedMessage:
    """Redact identifiers from one standalone transient message.

    Args:
        message: Validated user message held only in process memory.

    Returns:
        Transient minimized text and the candidate categories that were found.

    Notes:
        The rules intentionally cover Spanish identity documents, Spanish
        IBANs, Spanish phone numbers, online identifiers, IP addresses, and
        generic long numeric candidates. Shape-based detection does not
        authenticate a document or validate its checksum. Regex-based
        reduction cannot guarantee anonymity or detect every name, address,
        rare identifier, or identifying combination in free text.
    """
    return _minimize_message_with_registry(
        message=message,
        placeholder_registry={},
    )


def minimize_messages_for_provider(
    messages: tuple[str, ...],
) -> tuple[MinimizedMessage, ...]:
    """Minimize related texts with coherent request-local placeholders.

    Args:
        messages: Validated target and context values from one request.

    Returns:
        Minimized values in input order with shared placeholder numbering.
    """
    # The registry exists only for this call: it preserves conversational
    # references without persisting or exposing the original identifiers.
    placeholder_registry: dict[IdentifierCategory, dict[str, str]] = {}
    return tuple(
        _minimize_message_with_registry(
            message=message,
            placeholder_registry=placeholder_registry,
        )
        for message in messages
    )


def detect_output_identifier_candidates(
    value: str,
) -> frozenset[IdentifierCategory]:
    """Detect forbidden identifier candidates without rewriting LLM output.

    Args:
        value: Schema-valid but untrusted provider text held in memory.

    Returns:
        The closed candidate categories detected by output-specific policy.
    """
    normalized = normalize_message_text(value)
    detected: set[IdentifierCategory] = set()

    if _URL_CANDIDATE.search(normalized):
        detected.add(IdentifierCategory.URL)

    for rule in _STANDARD_RULES:
        if rule.pattern.search(normalized):
            detected.add(rule.category)

    if _contains_valid_ip_candidate(normalized):
        detected.add(IdentifierCategory.IP_ADDRESS_CANDIDATE)

    return frozenset(detected)
