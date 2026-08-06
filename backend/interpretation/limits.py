"""Shared immutable limits for LLM prompts and deterministic validation."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from backend.preferences.models import InterpretationDetail


# Final: signals to type checkers that this name is a constant and 
# must not be reassigned.
# MappingProxyType: read-only proxy that prevents runtime mutation of the mapping.
INTERPRETATION_CHARACTER_LIMITS: Final[
    Mapping[InterpretationDetail, int]
] = MappingProxyType(
    {
        InterpretationDetail.BRIEF: 420,
        InterpretationDetail.STANDARD: 750,
        InterpretationDetail.DETAILED: 1200,
    }
)
MAX_INTERPRETATION_CHARACTERS: Final[int] = max(
    INTERPRETATION_CHARACTER_LIMITS.values()
)
