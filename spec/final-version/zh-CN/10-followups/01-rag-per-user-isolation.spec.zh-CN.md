# Spec FV10.1：RAG 按用户隔离

来源设计文档：
- [10.1 RAG 按用户隔离设计](../../../system_design/final-version/zh-CN/10-followups/01-rag-per-user-isolation.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修正其 FR-FV10-023、FR-FV10-033/034 提升相关需求）

---

## 1. 目的

修复知识库 RAG 里一个已确认的跨租户数据泄露问题：现在的 `KnowledgeDocument` 和 `RetrievalQuery` 都不携带任何身份信息，任何组织的任何用户都能检索到任何已提升或种子文档。本 Spec 定义修正后的契约：基础/系统知识继续按角色门槛、对所有人可见，跟现在一样；用户提升的知识默认只对提升者本人私有，只有通过 [Spec FV10.2](02-file-sharing-approval-workflow.spec.zh-CN.md) 的审批流程才能扩大可见范围。

## 2. 范围

**纳入范围：**
- 为 `KnowledgeDocument` 和 Postgres 的 `knowledge.documents` 表新增 `owner_user_id`。
- 为 `RetrievalQuery` 新增 `requesting_user_id`，并在 `InMemoryKnowledgeStore.retrieve()` 中强制生效。
- 更新 `KnowledgePromotionService.promote_file()`，写入归属信息。
- 验证种子/基础文档不受影响。

**不纳入范围：**
- 把可见范围从"仅所有者"扩大出去的共享授权机制（见 Spec FV10.2）。
- 对 `business_table_catalog.py` 或 `SqlObjectAccessPolicy` 的任何改动（来源设计文档已确认这是两套互不相关的机制）。
- 向量相似度打分逻辑的改动（本 Spec 只关心"哪些文档有资格参与检索"，不关心已有资格的文档如何排序）。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方（`business_user`、`analyst`、`admin`）。不引入新参与方；本 Spec 下每个参与方自己提升的内容默认对自己私有。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-037 | `KnowledgeDocument` 和 Postgres 的 `knowledge.documents` 表必须携带一个可为空的 `owner_user_id`。种子/基础文档的该字段必须为 `NULL`。 |
| FR-FV10-038 | `owner_user_id IS NULL` 的文档必须继续按现有的 `allowed_roles` 规则可检索，不受 `requesting_user_id` 影响。 |
| FR-FV10-039 | 设置了 `owner_user_id` 的文档，除非 `requesting_user_id == owner_user_id`，或请求者对该文档来源文件持有有效共享授权（Spec FV10.2），否则必须从 `retrieve()` 结果中排除。 |
| FR-FV10-040 | `KnowledgePromotionService.promote_file()` 在写入实时 `InMemoryKnowledgeStore` 和 Postgres 时，都必须把 `owner_user_id` 设为上传者的 `user_id`。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-011 | 并发负载下跨用户泄露必须为零：用户 A 的检索结果绝不能包含用户 B 名下的文档，需要用 A、B 两个用户对同一个共享 store 实例并发发起请求来验证。 |
| NFR-FV10-012 | 新增归属过滤不得改变基础文档（`owner_user_id IS NULL`）相对于改动前的检索延迟或排序结果。 |

## 6. 数据契约

### 6.1 `KnowledgeDocument`（扩展后）

```python
@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    owner_user_id: str | None = None   # 新增
```

### 6.2 `RetrievalQuery`（扩展后）

```python
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    question: str
    requesting_user_id: str            # 新增，必填
    metric_context: str = ""
    doc_type: str | None = None
    doc_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None
    user_role: str | None = None
    tags: tuple[str, ...] = ()
    top_k: int = 5
    query_embedding: tuple[float, ...] | None = None
```

### 6.3 Postgres 迁移

```sql
ALTER TABLE knowledge.documents ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_owner ON knowledge.documents(owner_user_id) WHERE owner_user_id IS NOT NULL;
```

`_load_knowledge_store_from_db` 必须在原有查询列基础上一并 SELECT `owner_user_id`，并传入 `KnowledgeDocument`。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-030 | 用户 A 把某文件提升进自己的知识层；A 之后提出匹配问题，能检索到该文档。 |
| AC-FV10-031 | 用户 B（不同用户，同组织）针对 AC-FV10-030 提出同样匹配的问题；B 的结果中不包含 A 的文档。 |
| AC-FV10-032 | 种子基础文档（`owner_user_id = NULL`）在角色符合其 `allowed_roles` 的前提下，不论谁来提问都始终可检索到。 |
| AC-FV10-033 | 进程重启（会通过 `_load_knowledge_store_from_db` 从 Postgres 重新加载 `InMemoryKnowledgeStore`）后，之前所有已提升文档的 `owner_user_id` 都保持不变。 |

## 8. 测试计划

### 8.1 单元测试 —— `InMemoryKnowledgeStore` 过滤逻辑

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-107 | unit | `requesting_user_id=U1` 调用 `retrieve()`，能返回 `owner_user_id=U1` 的文档。 |
| TC-FV10-108 | unit | `requesting_user_id=U2` 调用 `retrieve()`，即使问题文本高度匹配，也不会返回 `owner_user_id=U1` 的文档。 |
| TC-FV10-109 | unit | 任意 `requesting_user_id` 调用 `retrieve()`，都能返回 `owner_user_id IS NULL` 的文档（仍受现有 `allowed_roles` 检查约束）。 |
| TC-FV10-110 | unit | `save_document()` 接受 `owner_user_id=None`（基础文档）和设置了 `owner_user_id`（用户所有）两种 `KnowledgeDocument`，均不报校验错误。 |
| TC-FV10-111 | unit | 一篇归属 `U1` 的文档，在（打桩的）共享可见性检查报告"U2 已获授权"后，对 `U2` 变为可检索（这是 Spec FV10.2 的集成点；本测试用桩函数模拟共享查询）。 |

### 8.2 单元测试 —— 提升时的归属写入

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-112 | unit | `KnowledgePromotionService.promote_file()` 写入实时知识库的 `KnowledgeDocument`，其 `owner_user_id` 等于来源文件的 `user_id`。 |
| TC-FV10-113 | unit | `KnowledgePromotionService.promote_file()` 把 `owner_user_id` 持久化进 Postgres 的 `knowledge.documents` 行（真实 Postgres 测试，受 `DATABASE_URL` 环境变量保护，跟这个代码库现有的活库测试约定一致）。 |

### 8.3 集成测试 —— 通过 HTTP 验证跨用户隔离

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-114 | integration | 分析师 A 提升一个非结构化文件；A 发起 `/api/v2/chat/query`（不带 `file_ids`，触发 RAG 的问题），`evidence_list` 中出现该已提升文档。 |
| TC-FV10-115 | integration | 同一组织内的分析师 B 提出同样的问题，`evidence_list` 中**不**出现 A 提升的文档；两人的种子基础证据均不受影响。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-037 | AC-FV10-030, AC-FV10-033 | TC-FV10-110, TC-FV10-113 |
| FR-FV10-038 | AC-FV10-032 | TC-FV10-109, TC-FV10-115 |
| FR-FV10-039 | AC-FV10-031, AC-FV10-032 | TC-FV10-107, TC-FV10-108, TC-FV10-111, TC-FV10-114, TC-FV10-115 |
| FR-FV10-040 | AC-FV10-030 | TC-FV10-112, TC-FV10-113 |
| NFR-FV10-011 | AC-FV10-031 | TC-FV10-108, TC-FV10-115 |
| NFR-FV10-012 | AC-FV10-032 | TC-FV10-109 |

## 10. 实现说明

- `KnowledgePromotionService` 不需要新增构造参数就能满足本 Spec——`owner_user_id` 直接从已经传入 `promote_file()` 的 `UserUploadedFile.user_id` 推导。
- 第 6.1 节里的 `shared_visibility()` 解析逻辑（TC-FV10-111、TC-FV10-114）依赖 Spec FV10.2 的 `FileShareRecord` 扇出机制；在那个 Spec 实现之前，`shared_visibility()` 可以先打桩为永远返回空集，不会违反本 Spec 的验收标准。
