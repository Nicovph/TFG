"""Shared synthetic builders for interpretation backend tests."""


def valid_output_payload() -> dict[str, object]:
    """Return a complete schema-valid synthetic provider payload.

    Returns:
        A fresh mutable dictionary containing no personal data.
    """
    return {
        "interpretation": "Puede ser una petición indirecta.",
        "clear_reformulation": "Por favor, cierra la ventana.",
        "needs_more_context": False,
        "context_note": "",
        "signals": [
            {
                "kind": "possible_indirect_language",
                "explanation": "La pregunta funciona como una petición cortés.",
            }
        ],
        "visual_concepts": ["cerrar ventana"],
    }
