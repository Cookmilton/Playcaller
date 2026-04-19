"""Configuration errors for the warehouse (clear operator messages)."""


class WarehouseConfigError(RuntimeError):
    """Missing or invalid warehouse configuration (env, paths, URLs)."""
