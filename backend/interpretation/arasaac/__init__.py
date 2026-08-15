"""Stable public interface for ARASAAC visual support.

The package keeps provider schemas, semantic matching, HTTP handling, and
orchestration separate. Callers import only the names exported here so those
internal boundaries can evolve without coupling the interpretation service to
the external provider implementation.
"""

from .contracts import (
    ArasaacAttribution,
    AvailablePictogram,
    MissingPictogram,
    VisualSupportResult,
)
from .service import build_unavailable_visual_support, get_visual_support


__all__ = (
    "ArasaacAttribution",
    "AvailablePictogram",
    "MissingPictogram",
    "VisualSupportResult",
    "build_unavailable_visual_support",
    "get_visual_support",
)
