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

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV03-001 | seed 或上传的 document 可以 chunk、embedding、存储、搜索。 |
| AC-FV03-002 | A 租户不能检索 B 租户 document chunk。 |
| AC-FV03-003 | RAG response 对每个有证据支撑的结论包含 citation。 |
| AC-FV03-004 | 没有证据时返回 warning，不伪造 citation。 |
| AC-FV03-005 | embedding 和 search event 包含 trace id、org id、latency、provider metadata。 |

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

