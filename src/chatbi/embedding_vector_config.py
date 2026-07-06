"""Runtime wiring for final-version embedding/vector RAG."""

from __future__ import annotations

import os
from math import ceil
from time import perf_counter

from chatbi.core.runtime_config import RuntimeConfig
from chatbi.embedding_vector_rag import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVectorRagService,
    InMemoryVectorStore,
    MockEmbeddingClient,
)


class OpenAIEmbeddingClient:
    """Thin OpenAI embeddings client matching the EmbeddingClient protocol."""

    provider_name = "openai"
    _COST_PER_1K = 0.00002  # text-embedding-3-small pricing

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        import urllib.request, json as _json

        self._api_key = api_key
        self._model = model
        self._dimensions = 1536
        self._urllib = urllib.request
        self._json = _json

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started_at = perf_counter()
        payload = self._json.dumps(
            {"input": list(request.input_texts), "model": self._model}
        ).encode()
        req = self._urllib.Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        with self._urllib.urlopen(req, timeout=30) as resp:
            body = self._json.loads(resp.read())

        vectors = tuple(
            tuple(item["embedding"]) for item in sorted(body["data"], key=lambda x: x["index"])
        )
        token_count = body.get("usage", {}).get("total_tokens", 0)
        latency_ms = max(0, int((perf_counter() - started_at) * 1000))
        return EmbeddingResponse(
            vectors=vectors,
            provider=self.provider_name,
            model_name=self._model,
            dimensions=self._dimensions,
            token_count=token_count,
            estimated_cost=round(token_count / 1000.0 * self._COST_PER_1K, 8),
            latency_ms=latency_ms,
        )


def build_embedding_vector_rag_service_from_runtime_config(
    runtime_config: RuntimeConfig,
) -> EmbeddingVectorRagService | None:
    if runtime_config.vector_store_url is None:
        return None
    if runtime_config.vector_store_url != "memory://local-vector-store":
        raise ValueError(f"Unsupported vector store URL: {runtime_config.vector_store_url}")

    if runtime_config.embedding_provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = runtime_config.embedding_model or "text-embedding-3-small"
        embedding_client: object = OpenAIEmbeddingClient(api_key=api_key, model=model)
    elif runtime_config.embedding_provider == "mock":
        embedding_client = MockEmbeddingClient()
    else:
        raise ValueError(f"Unsupported embedding provider: {runtime_config.embedding_provider}")

    return EmbeddingVectorRagService(
        embedding_client=embedding_client,  # type: ignore[arg-type]
        vector_store=InMemoryVectorStore(),
        embedding_model_name=runtime_config.embedding_model,
    )
