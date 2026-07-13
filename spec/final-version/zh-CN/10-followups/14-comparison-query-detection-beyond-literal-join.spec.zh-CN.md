# Spec FV10.14：把"零行 Join 提示"的比较查询判断，扩展到字面 JOIN 语法之外

English version: [../../en/10-followups/14-comparison-query-detection-beyond-literal-join.spec.en.md](../../en/10-followups/14-comparison-query-detection-beyond-literal-join.spec.en.md)

来源设计文档:
- [10.14 把"零行 Join 提示"的比较查询判断，扩展到字面 JOIN 语法之外](../../../../system_design/final-version/zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.zh-CN.md)
- [Spec FV10.12：混合文件/数仓对比回答的证据相关性过滤与 Join 不匹配提示](12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md)(父 Spec；本 Spec 只修订 FR-FV10-085 的触发条件，不改动那份 Spec 里的其他任何需求)

本 Spec 是在它所描述的修复**之后**才写的，走的是 [Spec FV10.5](05-rag-only-routing-and-promotion-durability.spec.zh-CN.md) 和 [Spec FV10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.zh-CN.md) 用过的同一种顺序——这个缺陷是靠对一个真实的、重新构建过的 Docker 部署做实盘复现，当场发现并当场修复的，不是提前设计出来的。本 Spec 记录并锁定的是已经实现、已经验证过的行为。

---

## 1. 目的

[Spec FV10.12](12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md) 的 FR-FV10-085 用一次字面子串检查（`"join" in sql_text.lower()`）来判断一次联邦查询的空结果，是不是一次真正的跨数据源比较、值不值得标上"不确定"的提示。在 FV10.12 自己的修复已经落地之后，针对触发 FV10.12 的那个原始问题做了一次实盘复测，结果依然复现了那个"没有差异"的错误结论——因为模型针对"对比……并标出差异"这类问题生成的 SQL 用的是 `EXCEPT`，不是 `JOIN`，完全绕开了那道字面子串检查。本 Spec 把这道检查换成了真正决定"这个结果算不算模糊"的那个判断：这条查询有没有同时引用数仓表视图和文件视图——不管它用的是哪种 SQL 写法。

## 2. 范围

**范围内:**
- 把 `FederatedQueryAgent._compute_zero_row_join_caveat()` 的触发条件，从字面匹配 `"join"` 子串，改成检查生成的 SQL 文本里有没有同时引用两个数据源视图（`db_{table_name}`、`file_{file_id}`）。

**范围外:**
- FR-FV10-085 里的其他条件（结果为空、数仓侧数据源非空、文件侧数据源非空）——不变。
- 判断生成的对比 SQL 本身在语义上对不对——本 Spec 只管一个空结果该不该带提示，不管产出这个结果的查询写得好不好。详见来源设计文档第 5 节。
- 不改动相关性分数下限（`_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`）或它自己的已知限制，这两者都已经由 Spec FV10.12 管辖。

## 3. 参与者

复用父 Spec FV-10 第 3 节定义的参与者，不新增参与者。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-091 | `FederatedQueryAgent._compute_zero_row_join_caveat()` 必须通过检查生成的 SQL 文本里是否**同时**包含数仓表视图名（`db_{table_name}`）和至少一个已附带文件的视图名（`file_{file_id}`）这两个子串，来判断这是不是一次真正的跨数据源比较——**不得**靠搜索字面子串 `"join"` 来判断。这条需求取代 FV10.12 最初的触发条件；FR-FV10-085 的另外三个条件（结果为空、数仓侧数据源行数非零、文件侧数据源行数非零）保持不变。 |

## 5. 非功能需求

除上面的 FR-FV10-091 外，无其他非功能需求。

## 6. 数据契约

### 6.1 `FederatedQueryAgent._compute_zero_row_join_caveat()` — `src/chatbi/agents/federated_query_agent.py`

```python
def _compute_zero_row_join_caveat(
    self,
    connection: Any,
    *,
    rows: tuple[Mapping[str, Any], ...],
    sql_text: str,
    pg_table_name: str,
    structured_files: tuple[UserUploadedFile, ...],
) -> bool:
    if rows:
        return False
    references_business_table = f"db_{pg_table_name}" in sql_text
    references_a_file = any(
        f"file_{file.file_id}" in sql_text for file in structured_files
    )
    if not (references_business_table and references_a_file):
        return False
    if self._source_row_count(connection, f"db_{pg_table_name}") == 0:
        return False
    return all(
        self._source_row_count(connection, f"file_{file.file_id}") > 0
        for file in structured_files
    )
```

两个视图名检查都是对原始 `sql_text` 做单纯的子串匹配，跟有没有加引号无关——DuckDB 要求一条查询必须点出它注册时用的那个确切视图名（`db_{table_name}`、`file_{file_id}`）才能引用它，所以不管模型生成的是哪种 SQL 写法（`JOIN`、`EXCEPT`、`NOT EXISTS`、反连接子查询……），这道检查都站得住。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-104 | 给定一条用 `EXCEPT` 只比较文件视图和数仓表视图 `month` 列的生成 SQL（文本里任何地方都没有字面子串 `"join"`），针对两个都非空、在 `month` 上完全重合的测试数据，以及一个 0 行的最终结果，`FederatedQueryAgentOutput.zero_row_join_caveat` 应为 `True`。 |
| AC-FV10-105 | 给定一条只引用数仓表视图（完全没有引用任何文件视图）、返回 0 行的生成 SQL，`zero_row_join_caveat` 应为 `False`——跟 FV10.12 原本"AC-FV10-093 相邻"的行为保持不变，只是理由从"没有字面 join 关键词"变成了"这根本不是一次跨数据源比较"。 |

## 8. 测试计划

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-217 | unit | 复现实盘报告里的那次失败：一条只在 `month` 上做 `EXCEPT` 的 SQL 语句，两份非空、在 key 上重合但值不同的测试数据，0 行结果 → `zero_row_join_caveat is True`（AC-FV10-104）。实现为 `tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_for_an_except_comparison_with_no_literal_join_keyword`。 |
| TC-FV10-218 | regression | 一条只引用 `db_revenue` 的单表查询 → `zero_row_join_caveat is False`（AC-FV10-105）。实现为 `tests/test_federated_query_agent.py::test_zero_row_join_caveat_false_when_the_query_only_references_one_source`（从 FV10.12 原来的 `..._when_the_generated_sql_has_no_join` 改名而来；测试数据不变，理由已更新）。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-091 | AC-FV10-104, AC-FV10-105 | TC-FV10-217, TC-FV10-218 |

## 10. 实现注记

- 通过对 FV10.12 本来要修复的那个原始问题做实盘复测发现——用的是一个真实的、重新构建过的 Docker 部署（`docker compose build backend worker && docker compose up -d --no-deps backend worker`）和一个真实的 `gpt-4o-mini` LLM client——不是设计评审，也不是写单元测试时发现的。修复和测试是一起写出来的，之后又拿去对着实盘部署确认过；完整的复现过程见来源设计文档第 4 节。
- **导致第一次复测依然复现 bug 的是一个部署缺口，不是代码缺口。**第一次针对这个问题做复测的时候，FV10.12 的代码修复其实已经落进源码树了，但正在运行的 `backend`/`worker` Docker 容器，跑的是大约 26 小时前构建的镜像——`Dockerfile.backend`/`Dockerfile.worker` 是在构建时把源码 `COPY` 进镜像的，所以磁盘上的代码改动，在容器重新构建、重启之前，对正在运行的容器没有任何影响。这一点之所以被记录在这里、也记录在来源设计文档第 6 节，是因为它是第一次实盘验证会产生误导的原因，而不是因为它是本 Spec 这条需求本身的缺陷。
- 本 Spec 的可追溯性内容刻意写得很精简（一条 FR、两条 AC、两条 TC），因为它的范围就是对一条既有需求（FV10.12 的 FR-FV10-085）内部一个条件的单一、窄范围修正，不是一个新功能——这跟 [Spec FV10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.zh-CN.md) 给自己那次单一需求修正所用的"文档篇幅要跟改动范围相称"的判断是一致的。
