# Spec FV10.6：混选结构化/非结构化文件时的混合回答

来源设计文档：
- [10.6 混选结构化/非结构化文件时的混合回答设计](../../../../system_design/final-version/zh-CN/10-followups/06-hybrid-file-answering-for-mixed-selections.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 终于把它的 FR-FV10-023 和 FR-FV10-025 真正实现出来——这两条需求从父 Spec 写下来那天起就一直没建）
- [Spec FV10.5：纯文档问答路由与知识库提升的持久性](05-rag-only-routing-and-promotion-durability.spec.zh-CN.md)（本 Spec 用一个范围更窄的失败场景取代了 10.5 的 `NO_STRUCTURED_FILE_SELECTED`——见第 4 节 FR-FV10-066；并且原样复用了那份 Spec FR-FV10-057/058 里 `FileDataAgent`/`FederatedQueryAgent` 的结构化/非结构化拆分逻辑，未做改动）

---

## 1. 目的

Spec FV10.5 让 `FileDataAgent`/`FederatedQueryAgent` 在选中的 `file_ids` 里混了非结构化文件（PDF/DOCX/TXT/MD/PPTX）时不再崩溃：非结构化文件在生成 SQL 之前就被过滤掉，过滤完没有结构化文件剩下时会明确报错。那是一个有意为之的"别崩溃"修复，不是"答对"修复——一个附带的 PDF 本来能回答的问题，现在要么直接失败，要么（如果同时还选了个 CSV）PDF 被悄悄忽略。

本 Spec 定义下一步：从请求自己附带的非结构化文件里检索证据，跟结构化文件的 SQL 查询结果一起综合成一个回答——这是文件附件场景下，跟主编排器现在处理"为什么营收下滑了"这类问题（SQL 数据行 + 知识库 RAG 证据一起出现）完全对等的能力。这一步补上了父 Spec FV-10 的 FR-FV10-023（用户上传文件的 RAG 检索范围限定）和 FR-FV10-025（`📎 Uploaded` 证据标注），这两条需求在父 Spec 里写过，但从来没有真正实现。

## 2. 范围

**纳入范围：**
- 在决定怎么回答之前，先把一次对话查询的 `file_ids` 拆成结构化子集和非结构化子集。
- 从非结构化子集自己已经切片、算好向量的内容里检索证据，检索范围严格限定在这次请求的 `file_ids` 上——不是 Spec FV10.1 那个组织级已提升的知识库。
- 把结构化子集的 `table_result` 和非结构化子集的 `evidence_list` 里非空的部分综合成一个回答。
- 把来自请求范围内上传文件的证据跟知识库证据区分开——用已有的 `is_uploaded_file` 标记 + 标题前缀机制（第 6.3 节），不是新建一套。
- 针对"这次请求的所有非结构化文件内容当前都不可检索"这种情况，给一个独立、不装作没查到的明确状态（这跟 Spec FV10.5 第 7 节已经记录过的、`FileVectorSource` 进程内存不持久化那个限制是同一个问题）。

**不纳入范围：**
- 修复 `FileVectorSource` 底层的持久性缺口本身（Spec FV10.5 第 7 节的"已知限制"，这里原样继承，未做改动——见第 7 节）。
- 对 `InMemoryKnowledgeStore` 排序算法（`_rank_records`/`_keyword_score`/`_cosine_similarity`）的任何改动——原样复用，只是换了个更窄的候选集。
- 对 `GroundedAnswerSynthesizer.synthesize()` 函数签名的任何改动——它本来就能在一次调用里同时接受 `table_result` 和 `evidence_list`。
- 对 `AnswerAssemblyVerifier` 的任何改动——Spec FV10.5 的 FR-FV10-060 已经能接受仅靠证据支撑的回答。
- 请求范围内文件内容的提升、分享或组织级可见性（这些由 Spec FV10.1/FV10.2 单独治理；本 Spec 的检索只在这一次请求的生命周期内、私下对请求方自己已经过所有权校验的文件生效）。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-064 | `_handle_file_data_chat_query` 必须先根据每个文件在仓库里的记录，把请求的 `file_ids` 拆成结构化子集（`file_type == "structured"`，等价于 `schema_json is not None`）和非结构化子集（`file_type == "unstructured"`），再决定怎么回答。 |
| FR-FV10-065 | 当 FR-FV10-064 拆出的非结构化子集非空时，系统必须通过一个检索范围严格限定在这些 `file_ids` 上的检索器去取证据，对每一个都读取 `FileVectorSource.chunks_with_vectors_for_file()`。这次检索不得读取或写入 Spec FV10.1 用的组织级已提升知识库（`InMemoryKnowledgeStore` / Postgres 的 `knowledge.*` 系列表）。 |
| FR-FV10-066 | 最终回答必须综合结构化子集的 `table_result` 和非结构化子集的 `evidence_list` 里非空的那部分。只有当结构化子集没有产出 `table_result`、且非结构化子集的 `evidence_list` 为空（并且不是因为 FR-FV10-069 描述的原因）时，请求才应以 `NO_ANSWERABLE_FILE_SELECTED` 失败。这取代了 Spec FV10.5 FR-FV10-061 的 `NO_STRUCTURED_FILE_SELECTED` 失败场景——现在只有在也没有非结构化证据可以兜底时，那个失败场景才适用。 |
| FR-FV10-067 | FR-FV10-065 检索器产出的每一条 `EvidenceItem`，必须通过 `uploaded_file_evidence` 参数（不是 `knowledge_base_evidence`）传给 `ResultMerger.merge()`，这样它才会被打上 `SourcedEvidenceItem(is_uploaded_file=True)` 标记——这是这个代码库里本来就用来区分"请求范围内文件证据"和"知识库证据"的机制（见第 6.3 节）。它的 `source_id` 依然必须等于来源文件自己的 `file_id`（这个代码库里本来就带 `ufile_` 前缀），这对可追溯性有用，但系统真正用来区分两种证据的不是这个前缀。 |
| FR-FV10-068 | 响应的 `evidence_list` 里，任何被标记为 `is_uploaded_file=True` 的证据条目，其 `title` 必须带 `📎 ` 前缀，跟知识库证据不带前缀的 `title` 区分开——这必须复用 `_handle_file_data_chat_query` 证据负载构造里本来就有的标题前缀逻辑；本 Spec 不需要、也没有引入任何新的前端渲染逻辑。 |
| FR-FV10-069 | FR-FV10-065 的检索器，不得为任何一个还没被 `_validate_chat_query_file_ids` 针对请求方 `user_id` 的所有权和 `ready` 状态筛过一遍的 `file_id` 去检索 chunk——必须复用这个已有的筛查，不得再引入第二套授权检查。 |
| FR-FV10-070 | 如果非结构化子集里**每一个** `file_id`，`FileVectorSource.chunks_with_vectors_for_file(file_id)` 都返回空元组，系统必须返回 `FILE_CONTENT_UNAVAILABLE`，跟 `NO_ANSWERABLE_FILE_SELECTED`（FR-FV10-066）区分开，也要跟"内容确实可用、但检索结果就是零条相关"的情况区分开。部分可用的情况——请求的几个非结构化文件里有的能查到 chunk、有的查不到——必须只用查到 chunk 的那些文件继续走下去，不得仅因为其中一个文件没内容就整体返回 `FILE_CONTENT_UNAVAILABLE`。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-022 | 本 Spec 的改动不得改变"`file_ids` 全是结构化文件"（Spec FV10.5 的纯 SQL 路径，不变）或"`file_ids` 为空"（主编排器路径，不变；另见 Spec FV10.5 的 NFR-FV10-021，那是针对无 `file_ids` 问题路由路径的对等保证）这两种请求已分类出的行为、agent 选择或最终回答。 |
| NFR-FV10-023 | FR-FV10-065 新增的检索，必须严格限定在请求到的那些 `file_ids` 自己的 chunk 范围内——不管问题内容是什么，都不得扫描组织级知识库或任何其他用户的文件。 |

## 6. 数据契约

### 6.1 按文件类型拆分

```python
def split_file_ids_by_type(
    file_ids: tuple[str, ...],
    files_by_id: Mapping[str, UserUploadedFile],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """返回 (结构化文件的 file_ids, 非结构化文件的 file_ids)，各自保留
    在输入里的相对顺序。file_ids 里的每一个都必须已经是 files_by_id 的
    key——这个函数本身不做 FR-FV10-069 要求的那次所有权/就绪状态筛查，
    调用方必须保证这一步已经完成。"""
    structured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is not None)
    unstructured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is None)
    return structured, unstructured
```

### 6.2 `FileScopedRetriever`

```python
class FileScopedRetriever:
    """FR-FV10-065/069：RAG 证据的检索范围严格限定在这一次请求的
    file_ids 上，不是组织级已提升的知识库。不需要提升步骤，不需要
    admin 审批——文件所有权在调用这里之前，已经被
    _validate_chat_query_file_ids 校验过了。"""

    def __init__(self, vector_source: FileVectorSource) -> None:
        self._vector_source = vector_source

    def retrieve(
        self, *, question: str, file_ids: tuple[str, ...], top_k: int = 5
    ) -> tuple[EvidenceItem, ...]:
        """如果每一个 file_id 调 chunks_with_vectors_for_file() 都返回空，
        这里返回 ()——"没有可用内容"这种情况由上一层的调用方处理
        （FR-FV10-070），不在这里抛异常。"""
```

排序逻辑复用 `chatbi.knowledge` 里已有的关键词+向量打分函数（`keyword_overlap_score`/`cosine_similarity`/`text_embedding`——作为本 Spec 的一部分，从 `_keyword_score`/`_cosine_similarity` 去掉了下划线变成公开函数，因为它们现在有了模块外的第二个正当调用方），只是候选集换成了从 `chunks_with_vectors_for_file()` 的输出构建的，而不是 `InMemoryKnowledgeStore` 的文档/chunk 表——不新增排序算法。

### 6.3 证据来源标注——用的是已有机制，不是新约定

实现时的发现：`ResultMerger.merge()`（`src/chatbi/orchestration/result_merger.py`）本来就接受一个 `uploaded_file_evidence: tuple[EvidenceItem, ...] = ()` 参数，会把经过这个参数传入的每一条证据打上 `SourcedEvidenceItem(evidence=item, is_uploaded_file=True)` 标记，而 `_handle_file_data_chat_query` 里已有的证据负载构造逻辑，本来就会给任何 `is_uploaded_file=True` 的条目渲染出 `f"📎 {title}"`——这些都不需要重新搭建；只是一直没有任何调用方往这个 `uploaded_file_evidence` 参数里传过东西。FR-FV10-065 检索器的输出只需要传进这个已有的参数：

```python
merged = file_result_merger.merge(
    file_output=file_output,  # 或者 federated_output=...
    uploaded_file_evidence=uploaded_file_evidence,  # FileScopedRetriever 的输出
    knowledge_base_evidence=knowledge_base_evidence,  # 不变，Spec FV10.1 的组织级知识库
)
```

`EvidenceItem.source_id` 依然设成来源文件自己的 `file_id`（这个代码库里本来就带 `ufile_` 前缀——见 `UserUploadedFile.file_id`），这对可追溯性有用，但**系统真正用来区分两种证据的机制，是 `merge()` 那一刻根据证据是从哪个参数传进来的、打上的 `is_uploaded_file` 布尔标记——不是靠字符串匹配 `source_id` 的前缀。** 本 Spec 最初的构想（下面的 FR-FV10-067/068）设计的是一套基于 source_id 前缀的前端渲染方案；这套方案其实不需要建，因为一个更直接的机制早就存在，只是缺一个输入没被填上——所以完全不需要改动任何前端代码。

### 6.4 新增错误原因

```
NO_ANSWERABLE_FILE_SELECTED  —— FR-FV10-066：table_result 和 evidence_list 都没有
FILE_CONTENT_UNAVAILABLE     —— FR-FV10-070：所有非结构化文件的 chunk 查询都是空的
```

两者都走 Spec FV10.5 FR-FV10-061 为 `NO_STRUCTURED_FILE_SELECTED` 建立的同一条 `error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, ...)` 路径——按那份 Spec 的先例，是 400，不是 500。同样按那份先例，响应顶层的 `error.code` 两种情况都还是共用的 `REQ_INVALID_ARGUMENT`——`ApiErrorCode` 是所有接口共用的一个固定枚举，而且 `chat_query_v2` 的响应构造函数（`_v2_answer_payload`）只会透传一组固定的、已知的 `data` 字段，其它的一律悄悄丢弃。这两种情况只靠 `error.message` 的文字内容区分，跟 Spec FV10.5 区分 `NO_STRUCTURED_FILE_SELECTED` 和 `INVALID_GENERATED_SQL`/`QUERY_RESOURCE_EXCEEDED` 用的是同一套方式——不是靠一个单独的机器可读字段。

### 6.5 `_handle_file_data_chat_query` 控制流（修订版）

```python
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

table_result = run_structured_query(structured_ids, question) if structured_ids else None

evidence_list: tuple[EvidenceItem, ...] = ()
file_content_unavailable = False
if unstructured_ids:
    evidence_list = file_scoped_retriever.retrieve(question=question, file_ids=unstructured_ids)
    if not evidence_list and _all_chunks_empty(unstructured_ids):
        file_content_unavailable = True

if table_result is None and not evidence_list:
    code = "FILE_CONTENT_UNAVAILABLE" if file_content_unavailable else "NO_ANSWERABLE_FILE_SELECTED"
    return error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, message=..., trace_id=trace_id)

answer = answer_synthesizer.synthesize(
    question=question,
    safe_sql=sql_text or "",
    table_result=table_result or TableResult(columns=(), rows=()),
    evidence_list=evidence_list,
    ...
)
```

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-061 | 一次请求的 `file_ids` 里有一个结构化文件和一个非结构化文件，两者都有相关内容，返回的回答 `table_result` 非空**并且** `evidence_list` 非空**并且**引用了那个非结构化文件的 `source_id`。 |
| AC-FV10-062 | 一次请求的 `file_ids` 里只有一个非结构化文件，且它的内容能回答这个问题，请求成功（`200`），`table_result` 为空、`evidence_list` 非空——这正是本 Spec 之前会以 `NO_STRUCTURED_FILE_SELECTED` 失败的那种情况。 |
| AC-FV10-063 | 响应 `evidence_list` 里每一条来自请求范围内文件的证据，`source_id` 都以 `ufile_` 开头、`title` 都带 `📎 ` 前缀；每一条来自知识库的，`source_id` 都以 `doc_` 开头、`title` 不带前缀。 |
| AC-FV10-064 | 一次请求的 `file_ids` 全是结构化文件，回答结果（同样的 agent 调用、同样的 `table_result`）跟 Spec FV10.5 已有的回答方式完全一致——这种形状的请求不会进入任何新代码路径。 |
| AC-FV10-065 | 一次请求的 `file_ids` 全是非结构化文件、且都没有相关内容，只要至少有一个文件的 `chunks_with_vectors_for_file()` 返回了非空候选集，请求依然成功，返回低相关度或空的 `evidence_list`，是正常响应（不是 `FILE_CONTENT_UNAVAILABLE`）。 |
| AC-FV10-066 | 一次请求的 `file_ids` 全是非结构化文件、且每一个的 `chunks_with_vectors_for_file()` 调用都返回空元组，请求失败，`error.message` 跟 `NO_ANSWERABLE_FILE_SELECTED` 那种情况的消息文字能区分开——两种情况下 `error.code` 都是 `REQ_INVALID_ARGUMENT`，按 Spec FV10.5 已经确立的"只靠消息文字区分"的先例。 |
| AC-FV10-067 | 一次请求带两个非结构化 `file_ids`，其中一个能查到 chunk、另一个查不到，请求成功，只用查到 chunk 的那个的证据——不会仅仅因为两个文件里有一个没内容就以 `FILE_CONTENT_UNAVAILABLE` 失败。 |
| AC-FV10-068 | FR-FV10-065 的检索器永远不会被传入一个 `_validate_chat_query_file_ids` 会拒绝的 `file_id`——这一点通过代码结构本身来验证（检索器只会收到筛查通过之后的子集），不是靠检索器内部再做一次运行时检查。 |

## 8. 测试计划

### 8.1 单元测试——按文件类型拆分

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-163 | 单元 | `split_file_ids_by_type()` 对两个结构化 + 一个非结构化的混合输入，返回的第一个元组是那两个结构化的、第二个元组是那一个非结构化的，且都保持原始相对顺序。 |
| TC-FV10-164 | 单元 | `split_file_ids_by_type()` 对全是非结构化文件的输入，返回 `((), (所有 file_ids))`。 |

### 8.2 单元测试——`FileScopedRetriever`

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-165 | 单元 | `FileScopedRetriever.retrieve()` 针对一个文件的 chunk 检索，返回的 `EvidenceItem` 的 `source_id` 正确等于 `f"ufile_{file_id}"`，从一个多 chunk 的文件里正确提取（AC-FV10-063）。 |
| TC-FV10-166 | 单元 | `FileScopedRetriever.retrieve()` 给定两个 `file_ids`，只返回带这两个 `file_id` 标记的 chunk——即使同一个 `FileVectorSource` 实例里还存着第三个文件的条目，也绝不会混进来（NFR-FV10-023）。 |
| TC-FV10-167 | 单元 | 对同一个文件的两个 chunk，`FileScopedRetriever.retrieve()` 把文本跟问题更贴近的那个排在前面（复用 `knowledge.py` 已有的打分逻辑——这条测试锁定的是"确实在调用被复用的函数，而不是另外重新实现了一套打分"）。 |
| TC-FV10-168 | 单元 | 对所有 `file_ids` 的 `chunks_with_vectors_for_file()` 都返回 `()` 的情况，`FileScopedRetriever.retrieve()` 返回 `()`——候选集为空的情况由调用方处理（FR-FV10-070），这里不抛异常。 |

### 8.3 单元测试——回答合并

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-169 | 单元 | 给定一个非 `None` 的 `table_result` 和一个非空的 `evidence_list`，合并逻辑调用 `answer_synthesizer.synthesize()` 时两者都传了，不是只传其中一个（AC-FV10-061）。 |
| TC-FV10-170 | 单元 | 给定 `table_result=None` 和一个非空的 `evidence_list`，合并逻辑调用 `synthesize()` 时传 `table_result=TableResult(columns=(), rows=())` 加上那份证据——不会返回 `NO_ANSWERABLE_FILE_SELECTED`（AC-FV10-062）。 |
| TC-FV10-171 | 单元 | 给定 `table_result=None`、`evidence_list=()`、`file_content_unavailable=False`，合并逻辑返回 `NO_ANSWERABLE_FILE_SELECTED`。 |
| TC-FV10-172 | 单元 | 给定 `table_result=None`、`evidence_list=()`、`file_content_unavailable=True`，合并逻辑返回 `FILE_CONTENT_UNAVAILABLE`，不是 `NO_ANSWERABLE_FILE_SELECTED`（AC-FV10-066）。 |

### 8.4 集成测试——HTTP

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-173 | 集成 | `POST /api/v2/chat/query`，`file_ids` = [一个结构化 + 一个非结构化]，两者都有匹配内容，返回 `200`，`table_result` 非空，`evidence_list` 里有一条 `ufile_` 前缀的来源（AC-FV10-061）。 |
| TC-FV10-174 | 集成 | `POST /api/v2/chat/query`，`file_ids` = [只有一个非结构化文件]，其内容能回答这个问题，返回 `200`——回归验证：这不再像只有 Spec FV10.5 时那样返回 `400 NO_STRUCTURED_FILE_SELECTED`（AC-FV10-062）。 |
| TC-FV10-175 | 集成 | `POST /api/v2/chat/query`，`file_ids` = [一个非结构化文件]、它的向量源里没有对应 chunk，返回 `400`，`error.message` 能跟 `NO_ANSWERABLE_FILE_SELECTED` 那种情况的消息文字区分开（AC-FV10-066）。 |
| TC-FV10-176 | 集成 | `POST /api/v2/chat/query`，`file_ids` = [全是结构化文件]，跟只应用了 Spec FV10.5 改动、还没本 Spec 改动的版本对同一个请求的响应相比，`table_result`/`sql_text` 逐字节一致——这是针对 AC-FV10-064/NFR-FV10-022 的回归检查。 |

### 8.5 集成测试——证据标题标注

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-177 | 集成（HTTP） | `POST /api/v2/chat/query` 对一个混合结构化+非结构化的选择，返回的 `evidence_list` 里，来自非结构化文件的那条 `title` 带 `📎 ` 前缀，来自知识库的那些不带（AC-FV10-063、FR-FV10-068）。没有单独的前端测试——这个仓库没有前端测试框架（没有 `*.test.*` 文件，`frontend/package.json` 里也没有测试运行器），而且标注本身完全是后端做的（第 6.3 节），所以一条针对 `evidence_list[].title` 的 HTTP 级断言，就已经完整测到了实际的行为。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-064 | AC-FV10-064 | TC-FV10-163, TC-FV10-164 |
| FR-FV10-065 | AC-FV10-061, AC-FV10-062 | TC-FV10-165, TC-FV10-166, TC-FV10-167, TC-FV10-173, TC-FV10-174 |
| FR-FV10-066 | AC-FV10-061, AC-FV10-062, AC-FV10-065 | TC-FV10-169, TC-FV10-170, TC-FV10-171 |
| FR-FV10-067 | AC-FV10-063 | TC-FV10-165 |
| FR-FV10-068 | AC-FV10-063 | TC-FV10-177 |
| FR-FV10-069 | AC-FV10-068 | — （通过代码结构验证；见第 10 节） |
| FR-FV10-070 | AC-FV10-066, AC-FV10-067 | TC-FV10-168, TC-FV10-172, TC-FV10-175 |
| NFR-FV10-022 | AC-FV10-064 | TC-FV10-176 |
| NFR-FV10-023 | — | TC-FV10-166 |

## 10. 实现备注

- FR-FV10-069 没有专门的运行时测试用例，因为它是一个结构性保证，不是一个运行时分支：`FileScopedRetriever` 从来不会收到完整的 `file_ids` 列表，只会收到 `split_file_ids_by_type()` 拆出来的子集，而这个子集本身在 `_handle_file_data_chat_query` 运行之前，就已经只包含 `_validate_chat_query_file_ids` 筛查通过的 `file_id`（Spec FV-10 的 FR-FV10-015）。AC-FV10-068 把它记为"通过代码结构验证"正是这个原因——跟 Spec FV10.4 实现备注里对 FR-FV10-056 的处理是同一个逻辑（"没有一个改写步骤"这件事本身没有直接的正向测试，只有一条如果真加了改写步骤就会失败的调用次数回归测试）。
- FR-FV10-070 里"部分可用的情况下不得返回 `FILE_CONTENT_UNAVAILABLE`"这一句之所以存在，是因为一个看起来顺理成章、实则错误的实现方式，是去检查"`evidence_list` 是不是空的"，而不是"是不是每一个文件的查询都返回了零个 chunk"——只有一个非结构化文件时这两个条件是等价的，但两个或更多文件时会分道扬镳：其中一个文件查不到内容，不应该盖过另一个文件确实有内容这件事。TC-FV10-168 以及 AC-FV10-067 隐含的部分可用场景，就是用来抓住"退化回那个更简单但错误的判断条件"这类回归的测试。
- 本 Spec 的 `NO_ANSWERABLE_FILE_SELECTED` 和 `FILE_CONTENT_UNAVAILABLE` 是刻意设计成两个不同的错误码、而不是合并成一个，正是因为它们对应的用户侧引导不一样：前者（"这里没有任何东西能回答你的问题"）应该让用户换一个文件，后者（"这个文件的内容现在检索不了"）应该让用户重新上传——把两者混在一起，无论哪种情况都会有一半的提示信息是错的，这跟 Spec FV10.5 第 6 节用来论证"`FileNotPromotableError` 优于悄悄创建一份文档"的理由是同一套逻辑。
- 本测试计划里没有任何用例重新验证 Spec FV10.5 里 `FileDataAgent`/`FederatedQueryAgent` 内部的结构化/非结构化拆分逻辑（那份 Spec 的 FR-FV10-057/058）——本 Spec 的 `split_file_ids_by_type()`（第 6.1 节）是在更高的一层起作用，在 `_handle_file_data_chat_query` 内部、在任何一个 agent 被调用之前，而且完全没有改变这些 agent 拿到结构化子集之后（它们本来就只会拿到结构化子集）做的事情。
- FR-FV10-067/068 最初设计的 source_id 前缀方案（见[来源设计文档](../../../../system_design/final-version/zh-CN/10-followups/06-hybrid-file-answering-for-mixed-selections.zh-CN.md)），真正开始实现之后发现是不需要的：`ResultMerger.merge()` 本来就有一个 `uploaded_file_evidence` 参数、一套 `is_uploaded_file` 标记+标题前缀的机制，就是为了这个目的建的，只是一直没人往里面喂东西。第 6.3 节记录了这个修正。这一点值得专门写出来，因为它把 FR-FV10-068 的"做完"标准从"写一套新的前端渲染逻辑"变成了"把一个已有的参数正确地填上"——比 Spec 原本暗示的改动要小、风险要低得多，这也是本 Spec 的实现完全没有改动 `frontend/src/App.tsx` 的原因。
