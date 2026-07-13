# Spec FV10.2：文件分享审批流程

来源设计文档：
- [10.2 文件分享审批流程设计](../../../system_design/final-version/zh-CN/10-followups/02-file-sharing-approval-workflow.zh-CN.md)
- [Spec FV10.1：RAG 按用户隔离](01-rag-per-user-isolation.spec.zh-CN.md)（依赖：审批会扩大该 Spec 定义的 RAG 可见范围）
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修正其 FR-FV10-026/027/033 里"管理员主动提升"的部分）

---

## 1. 目的

把"管理员主动提升文件"改成"分析师主动申请、管理员审批"的流程，并把分享的粒度精确定义为"同一个组织内、跟申请者角色相同的人"，而不是"整个组织"。

## 2. 范围

**纳入范围：**
- `FileShareRequest` 记录及其状态机（`pending` → `approved` | `rejected`）。
- `POST /api/v2/files/{file_id}/share-requests`。
- `GET /api/v2/admin/share-requests`、`POST .../approve`、`POST .../reject`。
- 扇出逻辑：解析出"申请者所在组织里、跟申请者角色相同的所有用户"。
- 当被分享的文件是非结构化且已被提升时，审批通过作为副作用，扩大对应 `KnowledgeDocument`（Spec FV10.1）的可见范围。

**不纳入范围：**
- 用户自助提升进自己私有知识层（不变，不需要审批，属于父 Spec FV-10 提升功能里"私有层"的既有范围）。
- 对 `FileShareRecord` 本身结构或 `FileAccessChecker` 访问判断逻辑的任何改动——两者都原样复用，不修改。
- 通过邮件/Slack 等站外方式通知用户申请状态变化。

## 3. 参与方

| 参与方 | 本 Spec 新增能力 |
|---|---|
| 分析师 / 业务用户（文件所有者） | 可对自己拥有的文件提交一条待审批的分享申请。 |
| 管理员 | 在自己所在组织内审阅、批准/拒绝待处理的申请。 |

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-041 | 文件所有者可以调用 `POST /api/v2/files/{file_id}/share-requests`。如果该 `file_id` 已存在一条 `pending` 申请，系统必须返回 HTTP 409。 |
| FR-FV10-042 | 批准一条申请，必须为申请者所在 `org_id` 内、**在批准那一刻**持有申请者角色的每一个用户各创建一条 `FileShareRecord`。在批准之后才被授予该角色的用户不得被追溯授权。 |
| FR-FV10-043 | 如果被分享的文件是 `file_type=unstructured` 且 `promoted_to_doc_id IS NOT NULL`，批准还必须把该文档的 RAG 可见范围（按 Spec FV10.1 第 4 节的 `shared_visibility()`）扩大到 FR-FV10-042 定义的同一批扇出对象。 |
| FR-FV10-044 | 拒绝一条申请，必须不创建任何 `FileShareRecord`，必须不改变该文件现有的可见性，并且必须把状态设为 `rejected`，记录 `decided_by` 和 `decided_at`。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-013 | 审批扇出必须是事务性的：要么所有匹配用户都收到 `FileShareRecord` 且申请标记为已批准，要么一个都不创建、申请保持 `pending`（失败时不允许部分扇出）。 |
| NFR-FV10-014 | 用户对自己不拥有的文件提交分享申请时，必须按照父 Spec 的存在性隐藏规则（FR-FV10-036、NFR-FV10-005）返回 HTTP 403/404。 |

## 6. 数据契约

### 6.1 `FileShareRequest`

```python
@dataclass(frozen=True, slots=True)
class FileShareRequest:
    request_id: str          # 前缀 req_share_
    file_id: str
    requested_by: str        # user_id
    org_id: str
    role: str                # 申请时申请者的角色；即扇出目标
    status: Literal["pending", "approved", "rejected"]
    requested_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None
```

### 6.2 接口

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| `POST` | `/api/v2/files/{file_id}/share-requests` | `{}` | `201` 返回创建的 `FileShareRequest`；若已有待审批申请则 `409` |
| `GET` | `/api/v2/admin/share-requests?status=pending` | — | 待处理的 `FileShareRequest` 列表，限定在该管理员所在组织 |
| `POST` | `/api/v2/admin/share-requests/{request_id}/approve` | `{}` | `200`；按 FR-FV10-042/043 触发扇出 |
| `POST` | `/api/v2/admin/share-requests/{request_id}/reject` | `{"reason": str \| None}` | `200` |

### 6.3 所需新增的 PostgreSQL 表

```
file_share_requests
```

所需索引：
- `(file_id, status)` —— 用于强制"每个文件同时只能有一条待审批申请"（FR-FV10-041）
- `(org_id, status, requested_at DESC)` —— 用于管理员列表接口

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-034 | 文件所有者提交一条分享申请；在第一条还处于待审批状态时再次提交同一文件的申请，返回 HTTP 409。 |
| AC-FV10-035 | 批准之后，申请者所在组织里的每一个其他分析师（如果申请者是分析师，则仅限分析师）都能通过 `GET /api/v2/files/{file_id}` 访问该文件；同组织里一个不是分析师的管理员则不能。 |
| AC-FV10-036 | 批准一个已提升的非结构化文件的申请后，扇出集合内的同事在匹配的对话查询中能检索到该文件的 RAG 内容；扇出集合之外的同事则不能。 |
| AC-FV10-037 | 拒绝之后，除所有者本人外任何人都无法访问该文件，且该文件不存在申请之前不存在的 `FileShareRecord`。 |

## 8. 测试计划

### 8.1 单元测试 —— 申请生命周期

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-116 | unit | 对一个没有待审批申请的文件创建分享申请，成功并返回 `status=pending`。 |
| TC-FV10-117 | unit | 对一个已存在 `pending` 申请的文件再次创建分享申请，抛出冲突错误。 |
| TC-FV10-118 | unit | 前一条申请被 `approved` 或 `rejected` 之后，允许再次创建分享申请（限制的是"存在活跃的 pending 申请"，不是历史记录本身）。 |

### 8.2 单元测试 —— 审批扇出

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-119 | unit | 批准来自 `org_acme` 一名 `analyst` 的申请，会为 `org_acme` 内其他每一个 `analyst` 创建一条 `FileShareRecord`，不会为该组织内的 `admin` 或 `business_user` 创建。 |
| TC-FV10-120 | unit | 即使某用户跟申请者角色相同，只要 `org_id` 不同，批准申请也不会为其创建任何 `FileShareRecord`。 |
| TC-FV10-121 | unit | 批准一个结构化（非非结构化）文件的申请，会创建 `FileShareRecord`，但不会尝试任何 RAG 可见性扩大调用。 |
| TC-FV10-122 | unit | 批准一个已提升的非结构化文件的申请，会把对应 `KnowledgeDocument` 的可见范围扩大到跟 `FileShareRecord` 扇出完全一致的用户集合。 |
| TC-FV10-123 | unit | 拒绝一条待审批申请，创建零条 `FileShareRecord`，并设置 `status=rejected`、`decided_by`、`decided_at`。 |

### 8.3 集成测试 —— HTTP 流程

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-124 | integration | 完整 HTTP 流程：分析师上传并提升一份 PDF，申请分享，管理员批准，同角色同事的对话查询（不带 `file_ids`）能看到该文件的已提升证据；同组织的管理员账号看不到。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-041 | AC-FV10-034 | TC-FV10-116, TC-FV10-117, TC-FV10-118 |
| FR-FV10-042 | AC-FV10-035 | TC-FV10-119, TC-FV10-120, TC-FV10-124 |
| FR-FV10-043 | AC-FV10-036 | TC-FV10-121, TC-FV10-122, TC-FV10-124 |
| FR-FV10-044 | AC-FV10-037 | TC-FV10-123 |
| NFR-FV10-013 | AC-FV10-035 | TC-FV10-119 |
| NFR-FV10-014 | AC-FV10-034 | TC-FV10-116 |

## 10. 实现说明

- 扇出查询（"申请者所在 `org_id` 里角色为 `X` 的所有用户"）复用现有的 `AuthStore`；除了 `admin_update_roles_v2` 等现有管理员接口本来就隐含需要的用户列表能力之外，不需要再建新的用户查询能力。
- 本 Spec 有意没有为申请者定义一个"查看自己提交过的申请状态"的列表接口——这次暂不纳入范围；申请者目前只能通过观察文件是否变成可共享状态来间接得知结果。这里明确标注为一个大概率的快速后续需求，而不是被悄悄决定省略掉。
