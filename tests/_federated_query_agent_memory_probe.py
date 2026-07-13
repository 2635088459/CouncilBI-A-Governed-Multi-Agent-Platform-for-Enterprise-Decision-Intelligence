"""Standalone script run in an isolated subprocess by TC-FV10-034.

Not collected by pytest (no ``test_`` prefix). Deliberately triggers a
DuckDB out-of-memory condition inside ``FederatedQueryAgent.run()`` and
prints "RESOURCE_EXCEEDED_OK" only if the agent translated it into a
``QUERY_RESOURCE_EXCEEDED`` output instead of letting the process crash.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chatbi.agents import FederatedQueryAgent
from chatbi.files import (
    FederatedQueryAgentInput,
    InMemoryFileRepository,
    InMemoryObjectStorageAdapter,
    ParquetWriter,
    PostgresQueryContext,
    StructuredFileParser,
    UserUploadedFile,
    parquet_storage_key,
)
from chatbi.llm.types import LLMRequest, LLMResponse


@dataclass(slots=True)
class _MemoryBlowingLLMClient:
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text="SELECT list(i) FROM range(50000000) t(i)",
            model_name="mock-model",
            provider="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=1,
            finish_reason="stop",
        )


@dataclass(slots=True)
class _FixedPostgresRowSource:
    rows: tuple[Mapping[str, Any], ...]

    def fetch_rows(self, context: PostgresQueryContext) -> tuple[Mapping[str, Any], ...]:
        return self.rows


def main() -> None:
    repository = InMemoryFileRepository()
    storage = InMemoryObjectStorageAdapter()
    file = UserUploadedFile(
        file_id="ufile_forecast",
        org_id="org_1",
        user_id="user_1",
        original_name="forecast.csv",
        file_type="structured",
        mime_type="text/csv",
        size_bytes=1024,
        storage_key="org_1/user_1/ufile_forecast/forecast.csv",
        content_hash="hash_forecast",
        status="ready",
        scope="user",
        file_group_id="fgrp_1",
        version_number=1,
        is_latest=True,
        created_at=datetime.now(timezone.utc),
        schema_json={"columns": [{"name": "month", "type": "VARCHAR"}]},
        row_count=1,
    )
    repository.save(file)

    table = StructuredFileParser().parse_csv(b"month\n2026-01\n")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    ParquetWriter().write(table, temp_path)
    storage.put_object(parquet_storage_key(file.storage_key), temp_path.read_bytes())
    temp_path.unlink()

    agent = FederatedQueryAgent(
        repository=repository,
        storage=storage,
        llm_client=_MemoryBlowingLLMClient(),
        pg_row_source=_FixedPostgresRowSource(({"month": "2026-01", "actual_revenue": 1.0},)),
        memory_limit="50MB",
    )
    request = FederatedQueryAgentInput(
        file_ids=("ufile_forecast",),
        user_id="user_1",
        pg_context=PostgresQueryContext(
            table_name="revenue", columns=("month", "actual_revenue"), max_rows=200_000
        ),
        question="blow up memory",
        role="analyst",
        trace_id="trc_1",
    )

    output = agent.run(request)
    if output.error_code == "QUERY_RESOURCE_EXCEEDED" and output.table_result is None:
        print("RESOURCE_EXCEEDED_OK")
    else:
        print(f"UNEXPECTED_OUTPUT: {output}")


if __name__ == "__main__":
    main()
