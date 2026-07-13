# 10.6 混选结构化/非结构化文件时的混合回答

## 1. 解决的问题

[10.5](05-rag-only-routing-and-promotion-durability.zh-CN.md) 第 6 节修好了 `FileDataAgent`/`FederatedQueryAgent`：现在勾选一份非结构化文件（PDF/DOCX/TXT/MD/PPTX）——不管是跟结构化文件一起选，还是单独选——都不会再崩溃了：非结构化文件在生成 SQL 之前就会被过滤掉，如果过滤完没有结构化文件剩下可查，会返回一个明确的 `NO_STRUCTURED_FILE_SELECTED` 错误。那个修复是有意保守的：它只是让崩溃停下来，但从来没有真正利用过非结构化文件的内容去回答问题。一个用户同时上传了一份 CSV 和一份 PDF、问了个问题，得到的回答只来自 CSV，没有任何提示说 PDF 被悄悄丢掉了；如果他只选了那份 PDF，直接就是一个错误。

本文档设计的是下一步：当选中了非结构化文件时，从这些文件自己的内容里检索证据，把结构化查询结果和非结构化证据一起综合成**一个**回答——就跟主编排器现在处理"为什么营收下滑了"这种问题时（SQL 数据行 + 知识库 RAG 证据一起出现在同一个回答里）完全一样的做法。

## 2. 已经具备的基础

这个功能需要的三块东西，代码里已经有了，只是当初是为别的目的建的：

- **`FileVectorSource.chunks_with_vectors_for_file(file_id)`**（`src/chatbi/files/worker.py`）——某个文件已经切好片、算好向量的文本，按 `file_id` 索引。`FileProcessingWorker` 在文件上传处理时把它填进去；`KnowledgePromotionService.promote_file()`（10.5 第 6 节）本来就靠读它把文件内容复制进共享知识库。本设计复用的是同一次读取，只是换了个目的：直接搜索这一次请求里附带的文件，不需要经过"提升"这一步。
- **`GroundedAnswerSynthesizer.synthesize(question, safe_sql, table_result, evidence_list, ...)`**（`src/chatbi/answer_synthesis.py`）——本来就在同一次调用里同时接受 SQL 结果集和证据列表；这正是主编排器现在生成"SQL+RAG 组合回答"用的那套逻辑。在文件处理这条分支里同时算出 `table_result` 和 `evidence_list`、一起传给它，这个函数本身不需要改一行。
- **`AnswerAssemblyVerifier`**（10.5 第 5 节）——已经能接受"`sql_text`/`table_result` 为空、但 `evidence_list` 非空"的回答为合法。一个只选了非结构化文件（完全没选结构化文件）的回答，现在不需要再改动就能通过最终校验。
- **父 spec 早就写了这个需求，但从来没实现**：[Spec FV-10 第 4 节](../../../../spec/final-version/zh-CN/10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md) 的 FR-FV10-023——"RAG agent 检索用户上传的非结构化文件 chunk 时，必须按 `user_id + file_id` 做隔离过滤。"这条需求描述的正是这个功能——检索范围限定在请求方自己这次附带的文件，不是组织级已提升的知识库——而 FR-FV10-025 也早就规定了非结构化文件的证据卡片要带一个跟知识库证据不同的 `📎 Uploaded` 标签。这两条都没有真正接入 `_handle_file_data_chat_query`；本文档就是把它们实际建出来的设计。

## 3. 设计：先按类型拆分 `file_ids`，再决定怎么回答

`_handle_file_data_chat_query`（`http.py`）现在做的是一个二选一的判断：问题里如果提到一个能解析出来的业务表就走 `FederatedQueryAgent`，否则走 `FileDataAgent`——两者都只针对结构化文件做 SQL 查询。现在先做一次拆分：

```python
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, file_repository)
```

`structured_ids`（可能为空）继续走现有的 SQL 路径，不变。`unstructured_ids`（可能为空）是新增的：喂给第 4 节的检索器。两个集合都可能为空，但不可能同时为空（`_validate_chat_query_file_ids` 在到达这个 handler 之前就已经拒绝了空 `file_ids`，见 FR-FV10-020）。

## 4. 设计：`FileScopedRetriever`——复用知识库的打分逻辑，只是候选集变窄了

一个新的、很小的类，不是一套新的排序算法：

```python
class FileScopedRetriever:
    """FR-FV10-023：RAG 证据的检索范围严格限定在这次请求的 file_ids 上，
    不是组织级已提升的知识库。不需要提升步骤，不需要 admin 审批——这些
    文件本来就是请求方自己的，在到达这个 handler 之前已经做过所有权校验。"""

    def __init__(self, vector_source: FileVectorSource) -> None:
        self._vector_source = vector_source

    def retrieve(
        self, *, question: str, file_ids: tuple[str, ...], top_k: int = 5
    ) -> tuple[EvidenceItem, ...]:
        candidates = tuple(
            (file_id, chunk, vector)
            for file_id in file_ids
            for chunk, vector in self._vector_source.chunks_with_vectors_for_file(file_id)
        )
        ranked = _rank_by_relevance(question, candidates)  # 复用 knowledge.py 的打分逻辑
        return tuple(_evidence_item_from_chunk(file_id, chunk) for file_id, chunk, _ in ranked[:top_k])
```

排序算法本身——关键词重合度 + 基于 `text_embedding()` 的余弦相似度——不用重新发明：`InMemoryKnowledgeStore._rank_records`/`_keyword_score`/`_cosine_similarity`（`knowledge.py`）今天已经验证过对*已提升*知识库的候选集能正确工作（今天验证 Nimbus 定价文档检索时用的就是它）。`FileScopedRetriever` 调用的是同一套打分函数，只是候选集换成了从 `chunks_with_vectors_for_file()` 里取出来的内容——这是一次刻意做窄、成本很低的单次请求级查询，不是搭建第二个知识库。

## 5. 设计：把两条分支合并成一个综合回答

```python
table_result = run_structured_query(structured_ids, question) if structured_ids else None
evidence_list = file_scoped_retriever.retrieve(question=question, file_ids=unstructured_ids) if unstructured_ids else ()

if table_result is None and not evidence_list:
    return error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, message="...")

answer = answer_synthesizer.synthesize(
    question=question,
    safe_sql=sql_text or "",
    table_result=table_result or TableResult(columns=(), rows=()),
    evidence_list=evidence_list,
    ...
)
```

10.5 第 6 节里那个失败场景（`NO_STRUCTURED_FILE_SELECTED`）现在变成了一条更通用规则下的特例：只有当**两条分支都**没查到任何东西时，请求才失败，不再是"只要没有结构化文件就失败"。只选一份 PDF、问一个这份 PDF 真的能回答的问题，现在能成功了——在本设计之前，不管 PDF 内容是什么都会失败。

## 6. 设计：证据来源标注——`📎 Uploaded` 区别于知识库证据

父 spec 的 FR-FV10-025 早就规定了这个区分；之所以一直没实现，是因为压根没有任何东西产出过"请求范围内的文件证据"需要去区分。`FileScopedRetriever` 产出的 `EvidenceItem` 带一个标记（比如 `source_id` 用 `ufile_` 前缀——就是文件自己的 ID，跟每个已提升知识库文档统一用的 `doc_` 前缀区分开），前端的 `EvidenceSection` 读到这个前缀就渲染成 `📎 Uploaded` 徽章，而不是知识库证据用的那种朴素来源标题。`EvidenceItem` 不需要加新字段——现有的 `source_id` 命名习惯本身就带着这个区分，前端只需要按前缀分支渲染，跟它现在给 `table_result_source === "file"` 渲染 `📎 File data` 徽章的做法是同一套逻辑。

## 7. 已知限制——继承了 10.5 里那个没解决的持久性缺口

`FileScopedRetriever` 读的还是那同一个 `FileVectorSource`——10.5 第 7 节已经记录过它"只存在于进程内存里、backend 一重启就没了"的特性,而且当时没有修。一份状态是 `ready` 的非结构化文件,如果它的 chunk 是在之前某个进程生命周期里生成的,这里查出来的候选集就会是空的,跟提升时遇到的情况一样。按照 10.5 里的处理模式（大声报错，不要悄悄地少给东西）：如果所有请求到的非结构化文件的 `chunks_with_vectors_for_file(file_id)` 都返回空,本设计要把这个当成一个独立的、明确的状态呈现出来（比如 `FILE_CONTENT_UNAVAILABLE`），而不是一个空的 `evidence_list`——那样看起来会跟"文档里确实没提到这个"没法区分。这跟 10.5 里为"提升"这个操作修的那个问题是同一种失败模式,在这里又出现了一次,因为背后是同一个数据源，而本文档同样没有修复这个持久性缺口本身。

## 8. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-064 | `_handle_file_data_chat_query` 必须先根据文件仓库里记录的 `file_type`/`schema_json`，把 `file_ids` 拆成结构化子集和非结构化子集，再决定怎么回答。 | 已实现——详见 spec |
| FR-FV10-065 | 当非结构化子集非空时，系统必须通过一个检索范围严格限定在这些 `file_ids` 上的检索器去取证据，数据来自 `FileVectorSource.chunks_with_vectors_for_file()`，不是组织级已提升的知识库。 | 已实现——详见 spec |
| FR-FV10-066 | 最终回答必须综合 `table_result`（结构化子集）和 `evidence_list`（非结构化子集）里非空的那些；只有当两者都为空时，请求才应失败。 | 已实现——详见 spec |
| FR-FV10-067 | 来自请求范围内上传文件的 `EvidenceItem` 必须能跟知识库证据区分开（比如通过 `source_id` 前缀），前端必须渲染出跟知识库证据卡片不同的 `📎 Uploaded` 标签，对应父 spec 的 FR-FV10-025。 | 已实现——详见 spec |
| FR-FV10-068 | FR-FV10-065 里的检索器不得检索请求方不拥有的 `file_id` 对应的 chunk——复用 `_validate_chat_query_file_ids` 在到达这个 handler 之前就已经做过的所有权校验，不需要新的授权机制。 | 已实现——详见 spec |
| FR-FV10-069 | 如果所有请求到的非结构化文件，`chunks_with_vectors_for_file()` 都返回空，系统必须呈现一个独立、明确的"内容当前不可检索"状态，不能是一个读起来像"文档里没提到这个"的空 `evidence_list`。 | 已实现——详见 spec |
| NFR-FV10-022 | 本设计不得改变"`file_ids` 全是结构化文件"（纯 SQL 路径，不变）或"完全没有文件"（主编排器路径，不变）这两种请求的现有行为。 | 已实现——详见 spec |

## 9. 现状：已实现

按本项目 SDD+TDD 的惯例，[Spec FV10.6](../../../../spec/final-version/zh-CN/10-followups/06-hybrid-file-answering-for-mixed-selections.spec.zh-CN.md) 把这份设计转化成了验收标准、测试用例和可追溯性矩阵，实现已经完成并测试过了。以准确的需求措辞而言，spec 才是权威、最新的来源——实现过程中发现了两处这份设计文档没预见到、也没体现的修正：

- 多了一条需求（spec 里的 FR-FV10-070），针对"部分可用"的情况——请求到的几个非结构化文件里，有的能查到 chunk、有的查不到——这份设计文档第 7 节讨论持久性问题时没有单独把这种情况点出来。
- 第 6 节设计的证据标注机制（这里的 FR-FV10-067/068）实际上本来就已经存在：`ResultMerger.merge()` 早就有一个 `uploaded_file_evidence` 参数、一套 `is_uploaded_file` 标记+标题前缀的机制，正是为了这个目的建的，只是一直没人往里面喂东西。spec 的第 6.3 节记录了这个修正——不需要任何新的前端代码，跟这份设计第 6 节暗示的不一样。
