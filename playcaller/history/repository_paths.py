"""Resolve the on-disk root for the app-managed history repository."""

from __future__ import annotations

from pathlib import Path

from .repository_settings import HistoryRepositorySettings


def resolve_history_repository_root(settings: HistoryRepositorySettings) -> Path:
    """Local-first default under the user home dir unless overridden via settings/env."""
    raw = (settings.repository_directory or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".playcaller" / "history_repository").resolve()


def ensure_repository_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "imports").mkdir(exist_ok=True)
    (root / "games").mkdir(exist_ok=True)
