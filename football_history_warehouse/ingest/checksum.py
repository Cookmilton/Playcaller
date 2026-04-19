"""
Content checksums for raw artifacts.

V1 uses SHA-256 hex digests (portable, audit-friendly). Callers may store
additional fingerprints in ``SourceArtifactRow.extra_metadata`` if a vendor
provides a stable id without bytes (e.g. ETag).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def sha256_hex(data: bytes) -> str:
    """Return lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_hex_iter(chunks: Iterable[bytes], *, chunk_size: int = 1 << 20) -> str:
    """
    Stream digest for large files without loading entirely into memory.

    If ``chunks`` is a single-element iterable of the full payload, behavior
    matches :func:`sha256_hex`.
    """
    h = hashlib.sha256()
    for part in chunks:
        if not part:
            continue
        h.update(part)
    return h.hexdigest()


def fingerprint_sha256_hex(data: bytes) -> str:
    """
    Alias for :func:`sha256_hex` — use when naming payloads in logs or metadata
    without implying a different algorithm.
    """
    return sha256_hex(data)
