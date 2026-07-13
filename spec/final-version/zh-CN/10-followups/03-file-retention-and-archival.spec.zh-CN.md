# Spec FV10.3：文件保留、自动归档与重新上传去重

来源设计文档：
- [10.3 文件保留、自动归档与重新上传去重设计](../../../system_design/final-version/zh-CN/10-followups/03-file-retention-and-archival.zh-CN.md)
- [Spec FV10.1：RAG 按用户隔离](01-rag-per-user-isolation.spec.zh-CN.md)（依赖：归档会让已提升的 RAG 内容失效）
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 替代其 FR-FV10-032 里破坏性的保留 Worker）

---

## 1. 目的

把破坏性、且从未被真正调度过的 `RetentionWorker` 替换成归档模型：更短的保留期（`user` scope 10 天，`team` scope 60 天）、保留字节和元数据但收回除 admin 外所有人访问权的归档状态、基于内容指纹的重新上传去重，以及真正生效的每日调度。

## 2. 范围

**纳入范围：**
- 缩短 `user`、`team` scope 的 `RETENTION_THRESHOLDS`。
- 新增 `archived_at` 字段，归档语义跟 `deleted_at` 区分开。
- `FileAccessChecker` 新增前置判断：归档文件不论所有权或共享授权，一律仅 admin 可访问。
- 新增 `content_hash` 字段，上传时计算，用于在重新上传时检测并清除重复的归档内容。
- 文件归档的同一时刻，让其已提升的 RAG 内容失效（Spec FV10.1）。
- 一个仅管理员可用的归档文件列表/导出接口。
- 让 `RetentionWorker.run()` 真正按每日至少一次的频率执行。

**不纳入范围：**
- 任何把归档内容加载进受治理业务数据库的管线——明确属于另一个团队的职责；本 Spec 只负责让归档内容可查看/可导出。
- `session` scope 保留期的改动（保持 24 小时不变）或 `org` scope 行为的改动（保持不变：不清理）。
- 分布式任务队列；本 Spec 的调度机制是一个进程内的周期性任务，不是引入新的基础设施。

## 3. 参与方

| 参与方 | 本 Spec 带来的行为变化 |
|---|---|
| 业务用户 / 分析师（文件所有者） | 自己的文件一旦归档就失去访问权；必须重新上传才能拿到可用的副本。 |
| 管理员 | 新增查看/导出全组织归档文件的能力；这是唯一能访问归档文件的角色。 |
| 后台 Worker | `RetentionWorker` 现在是归档而非清除，并且真正按调度运行。 |

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-045 | `RetentionWorker` 必须在 `last_accessed_at`（若从未被访问过则用 `created_at`）之后 10 天将 `user` scope 文件归档（而非清除），`team` scope 文件按同一参照时间点 60 天归档。 |
| FR-FV10-046 | 归档必须保留该文件的对象存储字节（原始文件及任何 Parquet 快照）以及其 Postgres 元数据行。归档那一刻两者都不能被删除。 |
| FR-FV10-047 | `FileAccessChecker.check()` 对 `archived_at IS NOT NULL` 的文件，除了该文件 `org_id` 内 `role == "admin"` 的请求者外，必须拒绝所有其他请求者，不论所有权或任何有效的 `FileShareRecord`。 |
| FR-FV10-048 | 归档一个 `promoted_to_doc_id IS NOT NULL` 的文件，必须把对应的 `KnowledgeDocument` 及其分块从实时知识库和 Postgres 中都移除（复用 `KnowledgePromotionService.demote_document()` 的移除逻辑），并清空该文件记录上的 `promoted_to_doc_id`。 |
| FR-FV10-049 | 每次新上传，系统必须计算 `content_hash`（原始字节的 SHA-256），如果匹配到同一个 `user_id` 名下的某个已归档文件，必须先清除该归档文件的对象存储字节并硬删除其元数据行，然后再继续处理这次新上传。 |
| FR-FV10-050 | `RetentionWorker.run()` 必须在实际运行的部署中通过真正的调度机制、以每 24 小时至少一次的频率执行（而不只是写好了却没人调用的代码）。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-015 | 归档必须是幂等的：对同一个已归档文件重复运行保留清扫，不能报错，也不能重复处理（比如不能尝试对一个已经降级过的 RAG 文档再次降级）。 |
| NFR-FV10-016 | 内容指纹的计算不得让上传响应时间超出父 Spec NFR-FV10-001 定义的现有上传延迟预算。 |
| NFR-FV10-017 | 去重匹配必须严格限定在"`content_hash` 相同**且**同一个 `user_id`"；即使字节完全相同，也不得跨用户匹配。 |

## 6. 数据契约

### 6.1 `UserUploadedFile`（扩展后）

```python
@dataclass(frozen=True, slots=True)
class UserUploadedFile:
    # ... 其余字段不变 ...
    content_hash: str                      # 新增 —— 原始上传字节的 SHA-256 十六进制摘要
    archived_at: datetime | None = None    # 新增 —— 跟 deleted_at 区分开
```

### 6.2 更新后的保留期阈值

```python
RETENTION_THRESHOLDS: dict[FileScope, timedelta] = {
    "session": timedelta(hours=24),   # 不变
    "user": timedelta(days=10),        # 原来是 30
    "team": timedelta(days=60),        # 原来是 90
}
```

### 6.3 访问权限矩阵（替代父 Spec 第 6.14 节）

| 条件 | 结果 |
|---|---|
| `file.archived_at IS NOT NULL AND role != 'admin'` | 拒绝，不论以下任何其他条件 |
| `file.archived_at IS NOT NULL AND role == 'admin' AND file.org_id == current_org_id` | 允许 |
| `file.user_id == current_user_id`（且未归档） | 允许 |
| `file.scope == 'org' AND file.org_id == current_org_id AND role IN ('analyst','admin')`（且未归档） | 允许 |
| `file.scope == 'team' AND 存在针对 current_user_id 的有效共享`（且未归档） | 允许 |
| `current_role == 'admin' AND file.org_id == current_org_id`（且未归档） | 允许 |
| 其他任何情况 | 拒绝 → HTTP 404（不暴露文件存在性，按父 Spec FR-FV10-036） |

### 6.4 接口

`GET /api/v2/admin/files/archived`（或者在现有 `GET /api/v2/admin/files` 上加 `status=archived` 筛选项）——仅管理员可用，返回全组织的归档文件，每条附带一个签名下载链接（复用现有的签名下载机制）。

### 6.5 Postgres 迁移

```sql
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE user_uploaded_files ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_content_hash ON user_uploaded_files(user_id, content_hash) WHERE archived_at IS NOT NULL;
```

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-038 | 一个 10 天无人访问的 `user` scope 文件被归档：`archived_at` 被设置，对象存储字节仍然存在，所有者调用 `GET /api/v2/files/{file_id}` 现在返回 HTTP 404。 |
| AC-FV10-039 | 一个 60 天无人访问的 `team` scope 文件在跟 AC-FV10-038 相同的条件下被归档，且之前持有其 `FileShareRecord` 的每个用户也一并失去访问权。 |
| AC-FV10-040 | 该文件所在组织的管理员能通过仅管理员接口检索并下载这个归档文件；非管理员（包括原所有者）即使通过同一个接口也不能。 |
| AC-FV10-041 | 归档一个已提升的文件，会让之前能看到它的任何用户在后续匹配的 RAG 查询中不再看到该证据，且该归档文件记录的 `promoted_to_doc_id` 读出来是 `None`。 |
| AC-FV10-042 | 对一个当前已归档的文件（同一上传者）重新上传字节完全相同的内容，之后只存在一条活跃文件记录（新上传的这条），该内容对应的归档记录清零；存储用量只反映这条新副本。 |
| AC-FV10-043 | 一个**不同**用户重新上传了跟另一用户归档副本字节相同的内容，不会清除对方用户的归档文件；之后既存在一条（未受影响的）归档记录，也存在一条新的活跃记录。 |

## 8. 测试计划

### 8.1 单元测试 —— 归档语义

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-125 | unit | 对一个 `last_accessed_at` 是 10 天前的 `user` scope 文件运行 `RetentionWorker.run()`，会设置 `archived_at`（而非 `deleted_at`），并且伪对象存储适配器里的文件字节保持不变。 |
| TC-FV10-126 | unit | 对一个 `last_accessed_at` 是 9 天前的 `user` scope 文件运行 `RetentionWorker.run()`，不会归档它。 |
| TC-FV10-127 | unit | `RetentionWorker.run()` 在 60 天而不是原来的 90 天阈值归档 `team` scope 文件。 |
| TC-FV10-128 | unit | 对一个已经归档过的文件第二次运行 `RetentionWorker.run()`，第二次是无操作（幂等性，对应 NFR-FV10-015）。 |

### 8.2 单元测试 —— 访问控制

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-129 | unit | 一旦 `archived_at` 被设置，`FileAccessChecker.check()` 会拒绝该文件的所有者本人，即使 `file.user_id == requester_user_id`。 |
| TC-FV10-130 | unit | 文件归档后，`FileAccessChecker.check()` 会拒绝持有有效 `FileShareRecord` 的用户。 |
| TC-FV10-131 | unit | 对一个归档文件，`FileAccessChecker.check()` 允许同一 `org_id` 内 `role == "admin"` 的请求者。 |

### 8.3 单元测试 —— 归档时 RAG 失效

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-132 | unit | 归档一个设置了 `promoted_to_doc_id` 的文件，会从 `InMemoryKnowledgeStore` 中移除对应的 `KnowledgeDocument`，并清空该归档记录上的 `promoted_to_doc_id`。 |

### 8.4 单元测试 —— 重新上传去重

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-133 | unit | 上传的内容指纹匹配同一用户名下的某个归档文件，会清除该归档文件的字节和元数据行。 |
| TC-FV10-134 | unit | 上传的内容指纹匹配**不同**用户名下的归档文件，不会清除任何东西；该归档文件保持不变。 |
| TC-FV10-135 | unit | 上传真正的新内容（指纹不匹配任何东西）永远不会触发任何清除。 |

### 8.5 集成测试 —— 调度

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-136 | integration | 应用启动后，会在一个有限的测试窗口内至少调用一次 `RetentionWorker.run()`（用测试专用的短间隔覆盖真实的 24 小时间隔，验证调度循环确实会触发，而不是真的等 24 小时）。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-045 | AC-FV10-038, AC-FV10-039 | TC-FV10-125, TC-FV10-126, TC-FV10-127 |
| FR-FV10-046 | AC-FV10-038 | TC-FV10-125 |
| FR-FV10-047 | AC-FV10-038, AC-FV10-039, AC-FV10-040 | TC-FV10-129, TC-FV10-130, TC-FV10-131 |
| FR-FV10-048 | AC-FV10-041 | TC-FV10-132 |
| FR-FV10-049 | AC-FV10-042, AC-FV10-043 | TC-FV10-133, TC-FV10-134, TC-FV10-135 |
| FR-FV10-050 | — | TC-FV10-136 |
| NFR-FV10-015 | — | TC-FV10-128 |
| NFR-FV10-016 | — | （复用父 Spec NFR-FV10-001 的上传延迟测试套件，开启哈希计算后重跑） |
| NFR-FV10-017 | AC-FV10-043 | TC-FV10-134 |

## 10. 实现说明

- 第 6.3 节的访问权限矩阵是对父 Spec 第 6.14 节的严格替代——归档前置判断必须最先检查，早于任何现有的所有权/scope 分支，否则一个归档文件的所有者会错误地通过 `file.user_id == current_user_id` 那一分支。
- 仅管理员可用的归档文件接口（第 6.4 节）在本 Spec 里刻意没有删除/恢复动作——从归档恢复不是一个已定义的工作流；回到"可用文件"状态的唯一路径就是重新上传（对应 FR-FV10-049 的上下文）。
