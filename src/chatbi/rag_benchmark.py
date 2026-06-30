"""Local benchmark helpers for RAG v2 retrieval.

This module is not a production metrics system. It gives tests, demos, and
manual verification one deterministic way to create many mock chunks and measure
retrieval latency against the spec's local-performance requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from chatbi.rag import EvidenceSearchRequest, IndexDocumentRequest
from chatbi.rag_indexing import ChunkSettings
from chatbi.rag_service import InMemoryRagService


@dataclass(frozen=True, slots=True)
class RagRetrievalBenchmarkResult:
    chunk_count: int
    run_count: int
    p95_latency_ms: float
    max_latency_ms: float
    evidence_count: int

    @property
    def meets_local_p95_target(self) -> bool:
        return self.p95_latency_ms <= 1500.0


def build_mock_rag_service(chunk_count: int = 1000) -> InMemoryRagService:
    """Build a deterministic service with roughly ``chunk_count`` chunks."""

    if chunk_count < 1:
        raise ValueError("chunk_count must be greater than or equal to 1")

    service = InMemoryRagService()
    text = " ".join(
        f"revenue campaign benchmark chunk token{index}"
        for index in range(chunk_count)
    )
    service.index_document(
        IndexDocumentRequest(
            document_id="doc_benchmark_revenue",
            source="benchmark-fixture",
            title="Benchmark revenue evidence",
            document_type="weekly_report",
            published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            business_tags=("revenue", "campaign", "benchmark"),
            permission_tags=("benchmark_reader",),
            text=text,
        ),
        chunk_settings=ChunkSettings(token_limit=5, overlap=0),
    )
    return service


def run_retrieval_benchmark(
    service: InMemoryRagService,
    run_count: int = 20,
    limit: int = 5,
) -> RagRetrievalBenchmarkResult:
    """Run repeated retrievals and return P95/max latency in milliseconds."""

    if run_count < 1:
        raise ValueError("run_count must be greater than or equal to 1")

    latencies_ms: list[float] = []
    evidence_count = 0
    for index in range(run_count):
        started_at = perf_counter()
        result = service.search_evidence(
            EvidenceSearchRequest(
                trace_id=f"trc_rag_benchmark_{index}",
                query_text="revenue campaign benchmark",
                time_window=None,
                business_tags=("revenue",),
                permission_tags=("benchmark_reader",),
                limit=limit,
            )
        )
        latencies_ms.append((perf_counter() - started_at) * 1000)
        evidence_count = len(result.evidence_list)

    sorted_latencies = tuple(sorted(latencies_ms))
    return RagRetrievalBenchmarkResult(
        chunk_count=service.state().indexed_chunk_count,
        run_count=run_count,
        p95_latency_ms=_percentile(sorted_latencies, 0.95),
        max_latency_ms=max(sorted_latencies),
        evidence_count=evidence_count,
    )


def _percentile(sorted_values: tuple[float, ...], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between 0.0 and 1.0")
    index = min(
        len(sorted_values) - 1,
        int(round((len(sorted_values) - 1) * percentile)),
    )
    return sorted_values[index]
