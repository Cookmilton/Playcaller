"""Fatal structural problems in ESPN summary JSON (caller may retry or quarantine)."""


class EspnSummaryParserError(ValueError):
    """Payload cannot be interpreted as an ESPN game summary (missing required nodes)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
