# Spec FV-03：Embedding 与 Vector RAG

来源设计：
- [Embedding 与 Vector RAG 设计](../../../system_design/final-version/zh-CN/04-embedding-vector-rag.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义真实文档 ingestion、embedding、vector storage、租户过滤检索和带 citation 的 RAG 行为。

## 2. 范围
范围内：
- 文档元数据、chunking、embedding、vector storage、search、rerank hook、context builder、citation。
- 每条 retrieval path 都必须做租户和权限过滤。
- deterministic mock embedding provider 和 vector store。

范围外：
- 完整文档编辑器或企业内容管理系统。
- 锁死某一个向量数据库厂商。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV03-001 | 系统必须定义 `EmbeddingClient` 和 `VectorStore` 抽象。 |
| FR-FV03-002 | 系统必须支持 deterministic mock embeddings。 |
| FR-FV03-003 | document 必须保存 `document_id`、`org_id`、source metadata、version、access policy。 |
| FR-FV03-004 | chunk 必须保存 `chunk_id`、`document_id`、`org_id`、text、token count、vector reference。 |
| FR-FV03-005 | query retrieval 必须先按租户过滤，再返回证据。 |
| FR-FV03-006 | RAG answer 必须包含使用过的 evidence chunk citation。 |
| FR-FV03-007 | 证据不足时，系统必须返回 missing-evidence warning，不能编造事实。 |
| FR-FV03-008 | embedding cost 和 latency 必须可观测。 |
| FR-FV03-009 | baseline vector store 必须提供 deterministic in-memory 实现，用于本地测试和 CI。 |
| FR-FV03-010 | RAG agent workflow 必须能通过注入的 retriever 使用 vector-store evidence，并且不能绕过 citation 校验。 |
| FR-FV03-011 | 系统必须暴露可复用 service facade，用于 document indexing、retrieval 和 citation-grounded answering。 |
| FR-FV03-012 | Runtime configuration 必须在 `VECTOR_STORE_URL=memory://local-vector-store` 时构建本地 embedding/vector RAG service。 |
| FR-FV03-013 | Document indexing API 必须能把 indexed chunks 写入已配置的 embedding/vector RAG service。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV03-001 | 10,000 个 mock chunk 的 vector search 本地 P95 应 <= 500ms。 |
| NFR-FV03-002 | 使用 mock embeddings 时检索测试必须 deterministic。 |
| NFR-FV03-003 | chunk size 必须有上限，控制 prompt token。 |
| NFR-FV03-004 | 删除或禁用的 document 不能被检索。 |

## 5. 契约
### 5.1 DocumentRecord
- `document_id: str`
- `org_id: str`
- `title: str`
- `source_type: str`
- `owner_user_id: str`
- `version: str`
- `access_policy: dict`
- `status: Literal["active", "deleted", "disabled"]`

### 5.2 EvidenceChunk
- `chunk_id: str`
- `document_id: str`
- `org_id: str`
- `text: str`
- `score: float`
- `citation: dict`

### 5.3 EmbeddingResponse
- `vectors: tuple[tuple[float, ...], ...]`
- `provider: str`
- `model_name: str`
- `dimensions: int`
- `token_count: int`
- `estimated_cost: float`
- `latency_ms: int`

### 5.4 Observability Event Metadata
Embedding event 必须包含：
- `trace_id`
- `org_id`
- `provider`
- `model`
- `latency_ms`
- `token_count`
- `estimated_cost`
- `input_count`

Vector search event 必须包含：
- `trace_id`
- `org_id`
- `provider`
- `latency_ms`
- `candidate_count`
- `returned_count`

### 5.5 Runtime 配置
本地 baseline 使用：
- `VECTOR_STORE_URL=memory://local-vector-store`：启用 in-memory vector store。
- `CHATBI_EMBEDDING_PROVIDER=mock`：使用 deterministic local embeddings。
- `CHATBI_EMBEDDING_MODEL=mock-local-embedding`：默认模型名，并支持环境变量覆盖。

不支持的 vector-store URL 或 embedding provider 必须在配置阶段明确失败。

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV03-001 | seed 或上传的 document 可以 chunk、embedding、存储、搜索。 |
| AC-FV03-002 | A 租户不能检索 B 租户 document chunk。 |
| AC-FV03-003 | RAG response 对每个有证据支撑的结论包含 citation。 |
| AC-FV03-004 | 没有证据时返回 warning，不伪造 citation。 |
| AC-FV03-005 | embedding 和 search event 包含 trace id、org id、latency、provider metadata。 |
| AC-FV03-006 | RAG agent 可以从 vector retriever 返回带 citation 的 evidence；无 vector evidence 时返回 uncertainty。 |
| AC-FV03-007 | Public RAG facade 导出 final-version embedding/vector RAG contracts，同时不破坏现有 v2 imports。 |
| AC-FV03-008 | Document indexing endpoint 可以把 document 持久化到配置好的 local vector RAG service，并通过问题检索回来。 |

## 7. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV03-001 | unit | chunker 保留 document id、org id、section、token count。 |
| TC-FV03-002 | unit | Mock embedding provider 返回稳定向量。 |
| TC-FV03-003 | integration | ingest document、embed chunks、search question、返回 evidence。 |
| TC-FV03-004 | integration negative | A 租户搜索不能返回 B 租户 chunk。 |
| TC-FV03-005 | integration negative | deleted document chunk 被排除。 |
| TC-FV03-006 | response | RAG answer citations 与返回 chunk 匹配。 |
| TC-FV03-007 | response negative | 无证据时返回 missing-evidence warning。 |
| TC-FV03-008 | benchmark | 10,000 mock chunks 的 vector search P95。 |
| TC-FV03-009 | integration | RAG agent 通过注入的 retriever 检索 vector evidence。 |
| TC-FV03-010 | integration negative | vector retrieval 无证据时，RAG agent 返回 uncertainty。 |
| TC-FV03-011 | unit | Embedding/vector RAG service 完成 indexing、retrieval 和 cited answer。 |
| TC-FV03-012 | contract | Public RAG facade 导出 final-version vector RAG service 和 contracts。 |
| TC-FV03-013 | unit | Runtime config 构建 memory vector RAG service，并保留 embedding model 配置。 |
| TC-FV03-014 | integration | Document index endpoint 写入配置好的 embedding/vector RAG service。 |

已实现测试覆盖：
- `tests/test_embedding_vector_rag.py`
- `tests/test_rag_agent.py`

已实现源码模块：
- `src/chatbi/embedding_vector_rag.py`

## 8. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV03-001 | AC-FV03-001 | TC-FV03-003 |
| FR-FV03-002 | AC-FV03-001 | TC-FV03-002 |
| FR-FV03-003 | AC-FV03-001 | TC-FV03-001 |
| FR-FV03-004 | AC-FV03-001 | TC-FV03-001 |
| FR-FV03-005 | AC-FV03-002 | TC-FV03-004 |
| FR-FV03-006 | AC-FV03-003 | TC-FV03-006 |
| FR-FV03-007 | AC-FV03-004 | TC-FV03-007 |
| FR-FV03-008 | AC-FV03-005 | TC-FV03-003 |
| FR-FV03-009 | AC-FV03-001 | TC-FV03-003, TC-FV03-008 |
| FR-FV03-010 | AC-FV03-006 | TC-FV03-009, TC-FV03-010 |
| FR-FV03-011 | AC-FV03-007 | TC-FV03-011, TC-FV03-012 |
| FR-FV03-012 | AC-FV03-008 | TC-FV03-013 |
| FR-FV03-013 | AC-FV03-008 | TC-FV03-014 |
| NFR-FV03-001 | AC-FV03-001 | TC-FV03-008 |
| NFR-FV03-003 | AC-FV03-001 | TC-FV03-001 |
| NFR-FV03-004 | AC-FV03-002 | TC-FV03-005 |
