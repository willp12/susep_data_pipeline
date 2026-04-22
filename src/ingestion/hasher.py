"""Streaming SHA256 for the raw SUSEP zip.

We hash on disk (not in memory) because ``BaseCompleta.zip`` is ~500 MB; a
straight ``.read()`` would spike resident memory unnecessarily on the runner.
The digest drives change-detection in ``ingestion_log`` — an identical hash
vs. the last successful run short-circuits the rest of the pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def sha256_file(path: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Return the hex SHA256 of ``path``, read in ``chunk_size`` chunks."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
