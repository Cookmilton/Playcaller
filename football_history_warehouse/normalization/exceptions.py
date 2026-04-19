"""Normalization failures that should stop the pipeline (operator-visible)."""


class NormalizationError(ValueError):
    """Parsed input cannot be mapped to canonical models with the given context."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
