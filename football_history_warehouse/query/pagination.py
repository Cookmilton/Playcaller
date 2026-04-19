"""Pagination primitives for list queries (offset/limit with a hard cap)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

# Tunable: batch UIs and exports can pass a lower limit; bulk jobs may raise the cap later.
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500


@dataclass(frozen=True, slots=True)
class PageParams:
    """
    Offset/limit page. ``limit`` is clamped logically by callers to ``MAX_PAGE_LIMIT``.

    **Extension:** add ``cursor`` / keyset pagination for very large seasons once needed.
    """

    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("offset must be non-negative")
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.limit > MAX_PAGE_LIMIT:
            raise ValueError(f"limit cannot exceed {MAX_PAGE_LIMIT}")


@dataclass(frozen=True, slots=True)
class PagedItems(Generic[T]):
    """One page of results plus ``has_more`` (cheap probe via limit+1 fetch)."""

    items: tuple[T, ...]
    limit: int
    offset: int
    has_more: bool
