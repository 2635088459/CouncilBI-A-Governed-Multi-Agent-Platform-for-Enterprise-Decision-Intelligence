"""Runtime wiring for final-version embedding/vector RAG."""

from __future__ import annotations

from chatbi.core.runtime_config import RuntimeConfig
from chatbi.embedding_vector_rag import (
    EmbeddingVectorRagService,
    InMemoryVectorStore,
    MockEmbeddingClient,
)


def build_embedding_vector_rag_service_from_runtime_config(
    runtime_config: RuntimeConfig,
) -> EmbeddingVectorRagService | None:
    if runtime_config.vector_store_url is None:
        return None
    if runtime_config.vector_store_url != "memory://local-vector-store":
        raise ValueError(f"Unsupported vector store URL: {runtime_config.vector_store_url}")
    if runtime_config.embedding_provider != "mock":
        raise ValueError(f"Unsupported embedding provider: {runtime_config.embedding_provider}")
    return EmbeddingVectorRagService(
        embedding_client=MockEmbeddingClient(),
        vector_store=InMemoryVectorStore(),
        embedding_model_name=runtime_config.embedding_model,
    )
