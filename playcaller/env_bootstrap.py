"""
Single place that loads repo-root ``.env`` into ``os.environ`` for this process.

**Why this module exists**

``load_dotenv()`` must run before any code reads ``FOOTBALL_WAREHOUSE_DATABASE_URL`` (or other
keys from ``.env``). Imports are cached in Python; an env var read at **module import time**
that runs before ``load_dotenv`` will see ``None`` for the whole session.

**Canonical trigger**

:func:`ensure_repo_dotenv_loaded` is invoked at the very start of ``playcaller/__init__.py``,
so the **first** ``import playcaller`` or ``from playcaller.…`` (Streamlit main, ``pages/*``,
tests, CLIs that import the package) applies ``.env`` before the rest of the package loads.

**Do not** add second ``load_dotenv()`` calls elsewhere “just in case” — use this entry only.
Streamlit’s main file still fixes ``sys.path`` before those imports; see ``streamlit_app.py``.
"""

from __future__ import annotations

from pathlib import Path

_LOADED = False


def ensure_repo_dotenv_loaded() -> None:
    """Parse ``<repo>/.env`` into the process environment (idempotent; no-op if python-dotenv missing)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
