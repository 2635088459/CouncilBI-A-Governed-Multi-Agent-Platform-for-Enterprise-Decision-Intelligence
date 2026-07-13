# 10.11 给文件 SQL 生成的 schema 上下文带上取值样本

## 1. 解决的问题

对 [10.8](08-question-relevance-gate-before-file-branch-routing.zh-CN.md)/[10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.zh-CN.md) 的路由修复做实盘验证时，用的是真实的 OpenAI LLM client，结果发现了一个相关但不同的缺陷。同一 session 里的一次追问——先问"What is my revenue by region?"，再问"What about just June?"——正确地留在了文件分支（路由本身没问题），但返回的 `table_result` 是空的。生成的 SQL 是：

```sql
SELECT region, SUM(revenue) AS total_revenue
FROM file_ufile_7b27e853fb394ba4818885d6a7b3a3ee
WHERE month = 'June'
```

而这份文件的 `month` 列实际存的是 `'2026-01'`..`'2026-06'`。0 行匹配——一个"合法但为空"的结果，跟 [10.7](07-cross-turn-value-format-contamination-in-file-sql-generation.zh-CN.md) 诊断出的*症状*一模一样，但*病因*不同：10.7 的修复（明确的 prompt 指示，加上更窄的对话历史窗口）只解决"取值格式是从*早前轮次*带过来的"这种情况。这次，"June"是直接打在*当前*这一轮问题里的——根本没有早前轮次可以怪罪，历史窗口再怎么调整也帮不上忙。模型猜了一个听起来合理的字面量，是因为它压根不知道这份文件实际存的是什么格式：`build_schema_context()` 之前只告诉它某一列的*名字*和*类型*（`month VARCHAR`），从来不会给它看这一列实际存的取值样本。

## 2. 已经具备的基础

- **`FileDataAgent.build_schema_context(files)`**（`src/chatbi/agents/file_data_agent.py`）——本来就负责从 `file.schema_json["columns"]` 构造出送进 SQL 生成 prompt 的那段字符串。这是这份设计改动的那个函数。
- **`FederatedQueryAgent._build_schema_context()`**——本来就把自己 schema 字符串里"文件那一侧"的部分委托给了 `self._file_data_agent.build_schema_context(files)`，"业务表那一侧"（`db_{table_name}(...)`）单独构造。扩展被委托的那个方法，会自动流转到联邦查询这条路径上，不需要在那边单独改代码——同样重要的是，这也让业务表那一侧完全不受影响，这一点在第 5 节会用到。
- **`SchemaSerializer.to_json(table)`**（`src/chatbi/files/parser_structured.py`）——本来就会在上传处理阶段（`FileProcessingWorker._process_structured`）算一次 `schema_json`，用的是已经完整解析进内存的 `table` 对象，早于它被写成 Parquet。这正是顺带算取值样本的天然位置：这时候整列数据已经在内存里了，完全不需要额外读文件或跑 DuckDB 查询——采样就是对已经为了推断 schema 而加载好的数据，做一次纯 Python 侧的运算。

## 3. 设计：样本在上传时算一次，而不是每次查询都算

不去在每一轮 chat 请求时都对文件的 Parquet 快照跑采样查询（那样会多几次 DuckDB 往返、给热路径增加延迟），样本在文件第一次被处理时，跟 schema 本身一起算好——也就是现在已经在计算列名和类型的那个节点：

```python
# src/chatbi/files/parser_structured.py
SAMPLE_CARDINALITY_THRESHOLD = 20
SAMPLE_SIZE = 5

class SchemaSerializer:
    def to_json(self, table: ParsedTable) -> dict[str, Any]:
        return {"columns": [self._column_json(column, table.rows) for column in table.columns]}

    def _column_json(self, column: ColumnSchema, rows: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": column.name, "type": column.type}
        if column.type != "VARCHAR":
            return entry  # 数值/日期类型没有这份设计要解决的那种歧义
        distinct = sorted({row[column.name] for row in rows if row.get(column.name) is not None})
        if not distinct:
            return entry
        if len(distinct) <= SAMPLE_CARDINALITY_THRESHOLD:
            entry["sample_values"] = distinct[:SAMPLE_SIZE]
        else:
            entry["sample_range"] = [distinct[0], distinct[-1]]
        return entry
```

这只会影响 `VARCHAR` 类型的列——像 `150000` 这样的 `BIGINT`/`DOUBLE` 取值，不存在日期字符串那种格式歧义；这份设计要解决的问题，本来就特指"一个字符串列，模型不得不去猜它的格式"这种情况。

`build_schema_context()` 则读取无论哪个键存在：

```python
# src/chatbi/agents/file_data_agent.py
def _column_def(self, column: Mapping[str, object]) -> str:
    piece = f"{column['name']} {column['type']}"
    if "sample_values" in column:
        examples = ", ".join(repr(value) for value in column["sample_values"])
        return f"{piece} [e.g. {examples}]"
    if "sample_range" in column:
        low, high = column["sample_range"]
        return f"{piece} [{low!r}..{high!r}]"
    return piece
```

对于触发问题的那份文件，它真实的 `month` 列有 6 个取值，这会产出 `month VARCHAR [e.g. '2026-01', '2026-02', '2026-03', '2026-04', '2026-05']`——第六个取值 `'2026-06'` 为什么没有字面出现，以及为什么这最终并不要紧，见第 4 节。

## 4. 一个在写测试时发现的、而不是在写代码时发现的偏差

触发问题的那份文件，它的 `month` 列刚好有 6 个去重取值（`'2026-01'` 到 `'2026-06'`）——远低于 `SAMPLE_CARDINALITY_THRESHOLD`（20），所以走的是 `sample_values` 分支，不是 `sample_range`。`SAMPLE_SIZE`（5）接着把这份列表截断成排序后的前五个——`'2026-01'`..`'2026-05'`——悄悄把 `'2026-06'` 丢掉了，而这恰恰是触发问题的那个问题（"What about just June?"）需要的那个值。

这意味着 schema 上下文里从来没有字面出现过一个正确的 `WHERE month = '2026-06'` 需要匹配的那个字符串。写端到端测试（第 6 节）的时候，比任何实盘验证都更早地暴露了这一点：一个天真的假 LLM client，如果只检查"prompt 里有没有出现目标字面量"，永远不会看到它——按这份设计最初草稿设想的样子（错误地假设 6 个取值的情况会走 `sample_range` 分支、揭示出一个 `'2026-01'..'2026-06'` 的范围），这条测试根本写不出来。假 client 的判断条件被重新设计成检查 schema 上下文*有没有揭示这一列的格式*（正则匹配一个类 ISO 日期的词元，比如 `\d{4}-\d{2}`），而不是检查*有没有包含被问到的那个具体字面量*——模拟的是一个能从样例里归纳出格式的模型，而不是一个必须逐字看到每一个取值的模型。

对着真实的 OpenAI LLM 做的实盘验证证实了这在实践中正是会发生的情况：给到 `month VARCHAR [e.g. '2026-01', '2026-02', '2026-03', '2026-04', '2026-05']`，再问"What about just June?"，模型正确地写出了 `WHERE month = '2026-06'`——从现有的五个样例里正确推断出了第六个值的格式，不需要它被字面列出来。这正是 `SAMPLE_SIZE` 这个参数存在时就已经暗含的假设（这份设计更早草稿的第 7 节问的是这两个常量"取值合不合适"，而不是问背后那个机制——从样例归纳——本身靠不靠谱）；这次实盘检查证实了，至少对这个案例，这个假设是对的。

## 5. 刻意不去动业务表那一侧

`FederatedQueryAgent._build_schema_context()` 里的 `db_line`——那条治理业务表的 schema 字符串——完全是单独构造的，数据来自 `PostgresQueryContext.columns`（已经经过 `business_table_catalog.py` 的 `safe_columns_for_role()` 拒绝/脱敏策略过滤），压根不会调用 `build_schema_context()`。这份设计的改动只会流经那次委托里"文件那一侧"的部分。这个分离是刻意的，不是顺带的：`safe_columns_for_role()` 只负责判断*schema 字符串里该出现哪些列*，并没有对应的策略去判断*某一列的真实取值能不能被展示出来*。一个被标记为 `mask` 策略的列（比如一个脱敏过的邮箱字段），即便它在"允许知道这一列存在"的集合里，如果这份设计被天真地也扩展到业务表那一侧，就会通过一条脱敏策略从来没设计要覆盖的路径，把真实取值泄露进 SQL 生成的 prompt 里。这份设计刻意把范围限定在用户自己上传的文件上——那些取值本来就会在执行完之后，通过 `answer_synthesis.py` 的落地上下文一起发给 LLM，所以不存在跨越新信任边界的问题——业务表那一侧留给未来一份独立的设计去处理（如果真的需要的话），而且那份设计需要先给 `access_policies` 扩展出一个"取值是否允许被采样展示"的标记，而不只是"列是否可见"的标记。

## 6. 验证

新增的单元测试：`SchemaSerializer.to_json()` 对低基数的 `VARCHAR` 列产出 `sample_values`，对高基数的产出 `sample_range`，对数值列两个键都不产出（`tests/test_structured_file_parser.py`）；`FileDataAgent.build_schema_context()` 正确渲染两种后缀，两个键都没有的列渲染得跟改动前一模一样（`tests/test_file_data_agent.py`）。两条既有的、对 `schema_json` 做逐字节相等断言的测试（`tests/test_structured_file_parser.py::test_schema_serializer_produces_columns_list_of_name_type_objects` 和 `tests/test_file_processing_worker.py::test_process_structured_file_produces_ready_status_schema_and_parquet_snapshot`）需要更新预期值、加上新的 `sample_values` 键——这是预期之中、刻意为之的行为变化，不是回归。

端到端测试（`tests/test_chat_query_with_files.py::test_a_month_literal_typed_into_the_current_question_uses_the_files_real_format`）用第 4 节描述的那个"看 prompt 内容决定输出"的假 LLM client，复现了第 1 节触发问题的那个场景，而且针对修复前的 `build_schema_context()` 会按预期失败。一条回归测试（`tests/test_federated_query_agent.py::test_business_table_schema_line_is_unaffected_by_a_files_value_samples`）确认了 `FederatedQueryAgent` 的 `db_line`，不管附带文件的 `schema_json` 里有没有取值样本，都逐字节一致。

在重新构建的 Docker 镜像上，用真实的 OpenAI LLM client 做了实盘复现：一份刚上传的文件，它的 `schema_json` 正确显示出了 `sample_values`（通过 `GET /api/v2/files` 验证）；第 1 节里那个同样的两轮 session——先问"What is my revenue by region?"，再问"What about just June?"——现在正确返回了六月真实的种子营收数字，模型正确地从现有的五个样例里推断出了 `'2026-06'`——在真实条件下证实了第 4 节的设计选择，不只是测试替身模拟出来的结果。

## 7. 已知限制——本次没有解决

- **`SAMPLE_CARDINALITY_THRESHOLD = 20` / `SAMPLE_SIZE = 5`依然是起步猜测**，没有拿真实文件的取值分布调过参。第 4 节展示了这个机制能容忍 `SAMPLE_SIZE` 把一个合法取值截断出列表之外（模型会去归纳格式而不是死记硬背）——但这只是针对一个真实场景、用一个真实 LLM 观察到的性质，不是对所有列形状的保证。一份有很多低基数 `VARCHAR` 列的文件，依然可能让 schema 字符串明显变长。
- **`sample_range` 依然会应用到所有高基数的 `VARCHAR` 列，包括自由文本列**（比如一个 `notes` 字段），会拿到一对技术上正确但没什么意义的 `[min..max]`。这无害——不是错的，只是没用——但一次便宜的预判（复用 [10.8](08-question-relevance-gate-before-file-branch-routing.zh-CN.md) 自己那种 `_GENERIC_DATE_TOKEN`/`_MONTH_NAME_TOKEN` 风格的判断逻辑，而不是重新发明一套），跳过那些不太可能受益的列，依然没有实现。
- **一列内部真的存在混杂格式的情况**（比如同一列里有的行是 `'2026-06'`、有的行是 `'June 2026'`，来自一次比较混乱的真实上传），依然要靠模型自己去调和不一致的样例——这份设计给模型的是一份能代表这一列实际存了什么的样本，不是保证它总能从中推断或调和出正确的格式。

## 8. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-080 | `SchemaSerializer.to_json()` 必须为每一个 `VARCHAR` 列，计算出一份不超过上限的去重取值样本列表（当去重后取值数量不超过配置的阈值时），或者一个 `[min, max]` 范围（超过阈值时）；这个计算必须在上传处理阶段、基于已经完整解析好的 table 只算一次，不能在每一轮 chat 里重新查询。 | 已实现 |
| FR-FV10-081 | `FileDataAgent.build_schema_context()` 必须在 `schema_json` 里存在 `sample_values`/`sample_range` 时，把它们渲染进送去做 SQL 生成的 schema 字符串里；两个键都不存在的列，渲染结果必须跟今天完全一致。 | 已实现 |
| FR-FV10-082 | 这项增强不得以任何方式改变 `FederatedQueryAgent` 的业务表（`db_{table_name}`）schema 字符串——只有它委托出去的、文件那一侧的 schema 上下文可以带上取值样本。 | 已实现 |
| NFR-FV10-028 | 这项增强不得在查询时额外增加 `FileDataAgent`/`FederatedQueryAgent` 现有流程之外的 DuckDB 往返查询，也不得要求给这次改动之前上传的文件回填 `schema_json`。 | 已实现 |

## 9. 现状：已实现并验证

按本项目通常的 SDD+TDD 顺序实现：先写好 [Spec FV10.11](../../../../spec/final-version/zh-CN/10-followups/11-value-sample-aware-schema-context.spec.zh-CN.md)，先写测试用例并确认它们真的在演练预期的行为，然后才改动 `SchemaSerializer`/`FileDataAgent` 让测试通过。第 4 节记录了写端到端测试时发现的一处真实偏差——这份设计更早的假设，跟触发问题的场景到底会走哪个分支（`sample_values` 还是 `sample_range`），跟按规格写出来的常量实际产出的结果不一致——在实现被判定完成之前就先修正了，之后又拿真实 LLM 确认过是靠谱的。修复涉及 `src/chatbi/files/parser_structured.py` 和 `src/chatbi/agents/file_data_agent.py`；`tests/test_structured_file_parser.py`、`tests/test_file_data_agent.py`、`tests/test_chat_query_with_files.py`、`tests/test_federated_query_agent.py` 里新增了对应测试，另外两条既有测试因为 `schema_json` 形状的刻意变化更新了预期值；按第 6 节所述，在重新构建的 Docker 镜像上、用真实 LLM provider 做了端到端验证。第 7 节列出的那些限制，是同一次工作中一并发现的，本次修复有意没有把它们纳入范围，留给未来的后续文档处理。
