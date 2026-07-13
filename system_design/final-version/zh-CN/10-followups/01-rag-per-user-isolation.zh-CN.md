# 10.1 RAG 按用户隔离

## 1. 解决的问题

现在的知识库 RAG Agent（`RagAgentRunner` → `InMemoryKnowledgeStore`）**完全没有租户或用户边界**。`KnowledgeDocument` 既没有 `org_id` 也没有 `owner_user_id`；`RetrievalQuery` 不携带任何身份信息；`_load_knowledge_store_from_db` 加载 `knowledge.documents` 时没有任何 `WHERE` 过滤条件。实际后果是：某个组织里分析师提升的文件、或者系统自带的种子文档，**任何组织的任何用户**只要问出匹配的问题，都能检索到。

这直接违背了这个平台"受治理的多租户"这个前提（`org_acme`、`org_techstart`、`org_globalretail` 本应互相隔离），而且不仅如此——用户上传部分的知识库还需要做到**按个人**隔离，而不只是按租户：一个分析师自己提升的文件内容，同组织的同事默认也不该看到，除非明确共享过（见 [10.2 文件分享审批流程](02-file-sharing-approval-workflow.zh-CN.md)）。

## 2. 两层知识

修复方式不是"把所有东西都改成私有"。现在知识库里的内容其实分两类，规则应该不一样：

| 层级 | 例子 | 归属 | 可见范围 |
|---|---|---|---|
| **基础/系统知识** | 15 篇种子公司文档（营收政策、季度业务回顾、指标定义、治理政策手册） | 不属于任何人——这是平台自带内容，不是用户上传的 | 不变：按现有的 `allowed_roles` 门槛（比如 `analyst`、`admin`），对应角色的所有人都能看到 |
| **用户上传的个人知识** | 分析师上传后自己提升进检索的文件 | 上传该文件的用户 | **默认私有**，只有本人能检索到，除非明确共享出去（见 10.2） |

基础文档**不会**因为这次改动或 [10.3 文件保留与归档](03-file-retention-and-archival.zh-CN.md) 而被归档或过期——它们是永久性平台内容，不受任何用户文件生命周期的约束。

## 3. 数据模型改动

`KnowledgeDocument`（`src/chatbi/knowledge.py`）新增一个字段：

```python
@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    source_id: str
    title: str
    doc_type: str
    publish_time: datetime
    tags: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    owner_user_id: str | None = None   # 新增。None = 基础/系统文档。
```

Postgres 的 `knowledge.documents` 表新增一个可为空的 `owner_user_id TEXT` 列（用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，跟这个代码库现有的迁移写法保持一致）。已有的种子数据行保持 `owner_user_id = NULL`。

`RetrievalQuery` 新增提问者的身份：

```python
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    question: str
    requesting_user_id: str            # 新增，必填
    ...  # 其余字段不变
```

## 4. 检索过滤逻辑

`InMemoryKnowledgeStore.list_chunk_records`（进而 `retrieve()`）在现有的 `doc_type`/`published_from`/`published_to`/`user_role`/`tags` 过滤条件之外，再加一条：

```
一篇文档对本次查询可见，当且仅当：
    document.owner_user_id is None                       # 基础知识：始终可见（仍受 allowed_roles 约束，跟现在一样）
    OR document.owner_user_id == requesting_user_id       # 提问者自己提升的内容
    OR requesting_user_id in shared_visibility(document)  # 通过 10.2 的审批流程被授予了可见性
```

`shared_visibility(document)` 不是 `KnowledgeDocument` 上新加的字段——它的推导方式跟文件访问权限本来的逻辑一致：一篇"可见范围被放宽"的文档，是指它所来源的**文件**本身对该用户存在有效的 `FileShareRecord` 授权（具体授权是怎么产生的，见 10.2）。知识库这一层完全不需要知道"文件"这个概念；HTTP 层在调用 `retrieve()` 之前，先判断"这个用户对这篇文档所来源的文件是否有共享授权"，把结果并入可见的 `owner_user_id` 集合（具体是扩大 `requesting_user_id` 匹配范围、还是别的实现方式，属于开工时再定的实现细节，不是设计上的分歧点）。

## 5. `owner_user_id` 由谁写入

- **种子/基础文档**：不变，`owner_user_id` 永远是 `NULL`。`scripts/seed_demo_data.sql` 不设置这个字段。
- **用户提升的文档**：`KnowledgePromotionService.promote_file()`（`src/chatbi/files/promotion.py`）在构建要写入实时知识库和 Postgres 的 `KnowledgeDocument` 时，设置 `owner_user_id=file.user_id`。这是对 [FV-10 提升功能](../10-user-file-upload-and-hybrid-analysis.zh-CN.md) 里已经建好的 `_index_into_live_rag` 辅助函数的一行改动。

## 6. 这次改动**不**涉及什么

- 提升到"仅自己可见"这一层依然不需要审批（10.1 只管**过滤逻辑**，不管"谁能提升"——分析师提升进自己私有层这件事本身，按 [10.2](02-file-sharing-approval-workflow.zh-CN.md) 的决定，不需要审批）。
- 联合查询的业务表目录（`business_table_catalog.py`）不受影响——它读的是实时 Postgres 的 `business.*` + `governance.access_policies`，跟知识库是完全独立的两套机制。
- `SqlObjectAccessPolicy`/`DataModelCatalog`（`chatbi/data_model.py`）不受影响——之前已经确认过它描述的是一套理想化 schema，跟实际部署的表对不上，也跟 RAG 没有关系。

## 7. 需求编号

| 编号 | 需求 |
|---|---|
| FR-FV10-037 | `KnowledgeDocument`/Postgres `knowledge.documents` 必须携带 `owner_user_id`，基础/系统文档该字段为 `NULL`。 |
| FR-FV10-038 | 基础文档（`owner_user_id IS NULL`）继续遵循现有 `allowed_roles` 规则，不受本次改动影响。 |
| FR-FV10-039 | 设置了 `owner_user_id` 的文档，只有该用户本人、或对其来源文件持有有效共享授权的用户才能检索到（见 FR-FV10-041 及后续）。 |
| FR-FV10-040 | 用户文件被提升时，`KnowledgePromotionService.promote_file()` 必须把上传者的 `user_id` 写入 `owner_user_id`。 |
