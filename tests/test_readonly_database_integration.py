import os

import pytest

from chatbi.governance import ReadOnlyDatabaseProbe, ReadOnlyProbeStatus
from chatbi.history.request_metadata import connect_psycopg


def test_readonly_database_url_cannot_create_guardrail_probe_table() -> None:
    readonly_database_url = os.environ.get("CHATBI_READONLY_DATABASE_URL")
    if not readonly_database_url:
        pytest.skip(
            "CHATBI_READONLY_DATABASE_URL is required for live read-only database "
            "integration."
        )

    probe = ReadOnlyDatabaseProbe(connect_psycopg)

    result = probe.check(readonly_database_url)

    assert result.status is ReadOnlyProbeStatus.BLOCKED
    assert result.passed is True
