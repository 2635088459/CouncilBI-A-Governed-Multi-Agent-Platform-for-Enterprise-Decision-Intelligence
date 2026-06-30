"""SQL hashing helpers for privacy-preserving audit records."""

from __future__ import annotations

import hashlib


class SqlHasher:
    """Create deterministic hashes for SQL text without storing plaintext SQL."""

    def hash(self, sql_text: str) -> str:
        return hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
