"""Ingest-layer errors (explicit; never use bare ``Exception`` for operator flow)."""


class IngestValidationError(ValueError):
    """Normalized ingest input failed validation (missing required fields, bad shape)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


class RawIngestError(RuntimeError):
    """
    Raw registration or persistence failed after validation.

    ``code`` is a stable machine string (logs, metrics); ``message`` is
    human-readable and safe to surface to operators.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
