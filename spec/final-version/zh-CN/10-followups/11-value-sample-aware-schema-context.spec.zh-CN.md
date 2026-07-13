# Spec FV10.11：给文件 SQL 生成的 schema 上下文带上取值样本

来源设计文档：
- [10.11 给文件 SQL 生成的 schema 上下文带上取值样本设计](../../../../system_design/final-version/zh-CN/10-followups/11-value-sample-aware-schema-context.zh-CN.md)
- [Spec FV-10：用户文件上传与混合数据分析](../10-user-file-upload-and-hybrid-analysis.spec.zh-CN.md)（父 Spec；本 Spec 修订 `SchemaSerializer.to_json()` 和 `FileDataAgent.build_schema_context()`，这两个都是在那份父 Spec 里第一次定义的）
- [10.7 文件/联邦查询 SQL 生成中的跨轮次取值格式污染设计](../../../../system_design/final-version/zh-CN/10-followups/07-cross-turn-value-format-contamination-in-file-sql-generation.zh-CN.md)——这一份也没有对应的独立 Spec FV10.7，它是直接从设计文档实现的，跟 10.8 的做法一样（见 Spec FV10.9 开头对同一模式的说明）。本 Spec 触发问题的那个失败场景（第 1 节），产出的*症状*跟那份设计文档诊断出的一模一样——取值格式不匹配导致"合法但为空"的 SQL——但*病因*不同，本 Spec 和那份文档的修复都没有关上对方的病因。

---

## 1. 目的

对 Spec FV10.9 路由修复做实盘验证时，用的是真实的 LLM provider，结果发现了一个跟 [10.7 设计文档](../../../../system_design/final-version/zh-CN/10-followups/07-cross-turn-value-format-contamination-in-file-sql-generation.zh-CN.md) 诊断出的缺陷同症状、不同病因的"表亲"问题。一次用户直接打在*当前*这一轮里的追问——"What about just June?"——针对一份 `month` 列存的是 `'2026-01'`..`'2026-06'` 的文件，产出了 `WHERE month = 'June'`：SQL 合法，0 行匹配。10.7 的修复（一条 prompt 指示加上一个更窄的对话历史窗口）在这里不适用——没有早前轮次可以怪罪；模型猜了一个听起来合理的字面量，是因为 `FileDataAgent.build_schema_context()` 之前只给它列的名字和类型，从来不给它看这一列实际存的取值样本。

本 Spec 定义的修复是：在文件上传处理阶段，为每一个 `VARCHAR` 列算一次一小组有代表性的取值（对于高基数的列，算一个取值范围），然后把它们带进送去做 SQL 生成的 schema 字符串里。

## 2. 范围

**纳入范围：**
- 扩展 `SchemaSerializer.to_json()`（`src/chatbi/files/parser_structured.py`），为每个 `VARCHAR` 列，从上传处理阶段已经完整解析进内存的 table 里，算出一份不超过上限的去重取值样本列表，或者一个 `[min, max]` 范围。
- 扩展 `FileDataAgent.build_schema_context()`（`src/chatbi/agents/file_data_agent.py`），渲染某一列 `schema_json` 条目里存在的那两者之一。
- 对于两个键都不存在的列——也就是本 Spec 之前上传的每一份文件的现状——`build_schema_context()` 的输出必须保持逐字节一致。

**不纳入范围：**
- 任何查询时的 DuckDB 采样——本 Spec 的采样只在上传时算一次，不是每一轮 chat 都算（第 6.1 节）。
- 对 `FederatedQueryAgent._build_schema_context()` 里业务表（`db_{table_name}`）schema 那一行的任何改动——本 Spec 的改动只会流经那个方法委托给 `FileDataAgent.build_schema_context()` 的文件那一侧（来源设计文档第 5 节；下面的 FR-FV10-082）。
- 给本 Spec 之前上传的文件回填 `schema_json`——一份已有文件在重新上传之前，会一直保持它现在（不带样本）的 schema 字符串。
- 针对真实文件的取值分布去调 `SAMPLE_CARDINALITY_THRESHOLD`/`SAMPLE_SIZE`，或者给自由文本列加一道预判、跳过不太可能受益的 `sample_range` 标注——这两个依然是来源设计文档（第 7 节）留给未来后续文档处理的开放问题，不是本 Spec 要锁定具体数值的需求。

## 3. 参与方

沿用父 Spec FV-10 第 3 节定义的参与方。不引入新参与方。

## 4. 功能需求

| 编号 | 需求 |
|---|---|
| FR-FV10-080 | `SchemaSerializer.to_json(table)` 对于每一个推断类型是 `VARCHAR` 的列，必须从这一列完整解析出来的取值里算出：当这一列去重后的取值数量不超过 `SAMPLE_CARDINALITY_THRESHOLD` 时，算出一份不超过 `SAMPLE_SIZE` 条的 `sample_values` 去重取值列表；超过时，算出一对 `sample_range`（按字典序取 `[min, max]`）。这个计算必须只算一次，用的是上传处理阶段已经在内存里的 `table` 对象，不得被任何在每次 chat 查询时运行的代码路径重新算一遍。一个没有任何非空取值的列，两个键都不得出现。一个推断类型不是 `VARCHAR` 的列，两个键都不得出现。 |
| FR-FV10-081 | `FileDataAgent.build_schema_context(files)` 对于每一列，必须先渲染 `f"{name} {type}"`，然后：如果 `schema_json` 里这一列的条目有 `sample_values` 键，追加 `f" [e.g. {sample_values...}]"`；如果有 `sample_range` 键，追加 `f" [{low}..{high}]"`；两个键都没有时，不追加任何后缀。 |
| FR-FV10-082 | 本 Spec 的改动，不得以任何方式改变 `FederatedQueryAgent._build_schema_context()` 的 `db_line`（那条从 `PostgresQueryContext.columns` 构造出来的业务表 schema 字符串），对任何输入都是如此。只有那个方法委托给 `FileDataAgent.build_schema_context()` 的文件那一侧，可以带上取值样本。 |

## 5. 非功能需求

| 编号 | 需求 |
|---|---|
| NFR-FV10-028 | 本 Spec 的改动，不得在 `FileDataAgent`/`FederatedQueryAgent` 现有的 chat 查询时流程之外，引入任何新的 DuckDB 查询，或者任何针对文件 Parquet 快照的新读取——FR-FV10-080 的计算必须完全包含在既有的上传处理流水线内（`FileProcessingWorker._process_structured()`，经由 `SchemaSerializer.to_json()`），这条流水线在本 Spec 改动之前、在行数上限检查（可能拒绝这次上传）之前，本来就已经把完整解析好的 table 存在内存里了。本 Spec 不得要求对本 Spec 实现之前上传的任何文件的 `schema_json` 做迁移或回填；`build_schema_context()` 必须把这类文件的列上没有 `sample_values`/`sample_range` 当作合法输入处理，不是一种错误。 |

## 6. 数据契约

### 6.1 `SchemaSerializer` —— 在上传时只算一次样本

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
            return entry
        distinct = sorted({row[column.name] for row in rows if row.get(column.name) is not None})
        if not distinct:
            return entry
        if len(distinct) <= SAMPLE_CARDINALITY_THRESHOLD:
            entry["sample_values"] = distinct[:SAMPLE_SIZE]
        else:
            entry["sample_range"] = [distinct[0], distinct[-1]]
        return entry
```

`to_json(table)` 读取的是 `table.rows`——跟 `FileProcessingWorker._process_structured()` 紧接着交给 `ParquetWriter.write()` 消费的、同一份已经在内存里、已经完整解析好的行数据。不需要新的文件读取，不需要新的 DuckDB 连接。

### 6.2 `FileDataAgent.build_schema_context()` —— 渲染样本

```python
# src/chatbi/agents/file_data_agent.py
def build_schema_context(self, files: tuple[UserUploadedFile, ...]) -> str:
    lines: list[str] = []
    for file in files:
        assert file.schema_json is not None
        columns = file.schema_json["columns"]
        column_defs = ", ".join(self._column_def(column) for column in columns)
        lines.append(f"file_{file.file_id}({column_defs})")
    return "\n".join(lines)

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

一个既没有 `sample_values` 也没有 `sample_range` 的列字典——也就是本 Spec 实现之前，每一份 `schema_json` 里每一列的现状——渲染结果必须跟本 Spec 实现之前完全一样：`f"{name} {type}"`，不带任何后缀。

## 7. 验收标准

| 编号 | 标准 |
|---|---|
| AC-FV10-080 | `SchemaSerializer.to_json(table)` 对一个解析出的取值里有 `N <= SAMPLE_CARDINALITY_THRESHOLD` 个去重非空字符串的 `VARCHAR` 列，产出的 `schema_json` 列条目应该有一个 `sample_values` 键，值等于排序后的去重取值，最多 `SAMPLE_SIZE` 个。 |
| AC-FV10-081 | `SchemaSerializer.to_json(table)` 对一个解析出的取值里有超过 `SAMPLE_CARDINALITY_THRESHOLD` 个去重非空字符串的 `VARCHAR` 列，产出的 `schema_json` 列条目应该有一个 `sample_range` 键，值等于按字典序排序后的 `[min(distinct), max(distinct)]`，且不应该有 `sample_values` 键。 |
| AC-FV10-082 | `SchemaSerializer.to_json(table)` 对一个 `BIGINT` 或 `DOUBLE` 列，产出的 `schema_json` 列条目应该既没有 `sample_values` 也没有 `sample_range` 键，不管这一列的基数是多少。 |
| AC-FV10-083 | `FileDataAgent.build_schema_context(files)` 对一份 `schema_json` 的 `region` 列条目带 `sample_values: ["US-East", "US-West"]` 的文件，返回的 schema 字符串里应该包含 `"region VARCHAR [e.g. 'US-East', 'US-West']"`（或等价的 `repr()` 引用形式）。 |
| AC-FV10-084 | `FileDataAgent.build_schema_context(files)` 对一份 `schema_json` 的 `month` 列条目带 `sample_range: ["2026-01", "2026-06"]` 的文件，返回的 schema 字符串里应该包含 `"month VARCHAR ['2026-01'..'2026-06']"`（或等价的渲染形式）。 |
| AC-FV10-085 | `FileDataAgent.build_schema_context(files)` 对一份 `schema_json` 的列条目两个键都没有的文件（也就是本 Spec 实现之前上传的文件的形状），渲染结果应该跟本 Spec 实现之前的输出完全一样——对每一个这样的列都是 `f"{name} {type}"`，不带后缀。 |
| AC-FV10-086 | 给定一份文件，它的 `month` 列种子数据是 `'2026-01'`..`'2026-06'`（6 个去重取值——低于 `SAMPLE_CARDINALITY_THRESHOLD`，所以按 AC-FV10-080，它的 `schema_json` 带的是 `sample_values`，截断成排序后的前 5 条，`'2026-01'`..`'2026-05'`，不是 `sample_range`——本 Spec 自己最初的草稿为什么假设是反过来的，见第 10 节），在一个上一轮已经查过这份文件的 session 里问"What about just June?"，应该产出一个非空的 `table_result`，行数据来自 6 月真实的种子数据——测试用的假 LLM client，需要配置成：只有在收到的 prompt 的 schema 上下文字符串揭示了这一列的日期格式时（不管是通过 `sample_values` 还是 `sample_range`，出现了一个类 ISO 日期的词元），才返回字面量正确的 `WHERE month = '2026-06'`，否则返回错误的 `WHERE month = 'June'`——这样一来，如果 FR-FV10-081 描述的 schema 上下文改动没有真正传到模型面前，这条测试就会失败。这个 client 的判断条件检查的是"格式有没有被揭示"，不是"目标字面量 `'2026-06'` 本身在不在"——对于这个具体的测试夹具，那个值本来就不会字面出现在样本里，这是刻意的（见第 10 节）。 |
| AC-FV10-087 | `FederatedQueryAgent._build_schema_context()` 针对同一个 `PostgresQueryContext`，返回的 `db_line`，不管一起传进去的文件的 `schema_json` 里有没有 `sample_values`/`sample_range` 条目，都应该逐字节一致——本 Spec 的改动，对那个方法输出里业务表那一半，不应该产生任何可观察的影响。 |

## 8. 测试计划

### 8.1 单元测试——`SchemaSerializer` 样本计算

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-189 | 单元 | `SchemaSerializer().to_json(table)` 对一份 `VARCHAR` 列种子数据是 4 条（`"US-West"`、`"US-East"`、`"US-West"`、`"EU"`）的解析表，产出的 `sample_values` 条目应该等于去重后的 3 个值，排好序（AC-FV10-080）。对应实现：`tests/test_structured_file_parser.py::test_schema_serializer_adds_sample_values_for_a_low_cardinality_varchar_column`。 |
| TC-FV10-190 | 单元 | `SchemaSerializer().to_json(table)` 对一份 `VARCHAR` 列种子数据是 30 个去重取值的解析表，产出的 `sample_range` 条目应该等于 `[sorted_values[0], sorted_values[-1]]`，且不应该有 `sample_values` 键（AC-FV10-081）。对应实现：`tests/test_structured_file_parser.py::test_schema_serializer_adds_sample_range_for_a_high_cardinality_varchar_column`。 |
| TC-FV10-191 | 单元 | `SchemaSerializer().to_json(table)` 对带 `BIGINT`/`DOUBLE` 列的解析表，产出的列条目应该没有 `sample_values`/`sample_range` 键（AC-FV10-082）。对应实现：`tests/test_structured_file_parser.py::test_schema_serializer_never_adds_sample_keys_to_a_numeric_column`。 |

### 8.2 单元测试——`FileDataAgent.build_schema_context()` 渲染

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-192 | 单元 | `FileDataAgent().build_schema_context(files)` 对一份 `schema_json` 的 `region` 列带 `sample_values: ["US-East", "US-West"]` 的文件，返回的字符串里应该包含 `"region VARCHAR [e.g. 'US-East', 'US-West']"`（AC-FV10-083）。对应实现：`tests/test_file_data_agent.py::test_build_schema_context_renders_a_sample_values_suffix`。 |
| TC-FV10-193 | 单元 | `FileDataAgent().build_schema_context(files)` 对一份 `schema_json` 的 `month` 列带 `sample_range: ["2026-01", "2026-06"]` 的文件，返回的字符串里应该包含 `"month VARCHAR ['2026-01'..'2026-06']"`（AC-FV10-084）。对应实现：`tests/test_file_data_agent.py::test_build_schema_context_renders_a_sample_range_suffix`。 |
| TC-FV10-194 | 单元 | `FileDataAgent().build_schema_context(files)` 对一份 `schema_json` 列两个键都没有的文件，产出的字符串应该跟 `FileDataAgent` 本 Spec 实现之前的输出逐字节一致（AC-FV10-085）——这是证明既有文件行为不受影响的回归测试。对应实现：`tests/test_file_data_agent.py::test_build_schema_context_reflects_schema_json`。 |

### 8.3 集成测试——把触发问题的那个失败场景修好

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-195 | 集成（HTTP） | 端到端复现本 Spec 第 1 节触发问题的那个场景：一个两轮 session，针对一份种子数据带 `region`/`month`/`revenue` 行（`month` 取值 `'2026-01'`..`'2026-06'`）的文件，第二轮问"What about just June?"，用的是按 AC-FV10-086 描述配置好的"看格式决定输出"的假 LLM client。断言 `table_result` 非空，且匹配 6 月的种子数据行（AC-FV10-086）。这条测试针对本 Spec 实现之前的 `build_schema_context()` 会失败，因为这个假 LLM client 被刻意配置成"只有在拿到揭示了这一列日期格式的 schema 字符串时才会给出正确的 SQL"——一个不管 prompt 内容如何都返回正确 SQL 的固定输出型测试替身，是没法抓住"退化回本 Spec 核心机制失效"这种回归的，这正是这条测试的假 client 要做成"看 prompt 内容决定输出"而不是"固定输出"的原因。对应实现：`tests/test_chat_query_with_files.py::test_a_month_literal_typed_into_the_current_question_uses_the_files_real_format`。 |

### 8.4 回归测试——业务表 schema 那一行不受影响

| 编号 | 层级 | 描述 |
|---|---|---|
| TC-FV10-196 | 回归 | `FederatedQueryAgent` 的 schema 上下文构造逻辑，分别用一份 `schema_json` 不带样本的文件、和一份 `schema_json` 带 `sample_range` 的文件各跑一次，针对同一个 `PostgresQueryContext`，产出的 `db_line`（也就是被记录下来的 SQL 生成 prompt 里、以 `db_{table_name}(` 开头的那个子串）两次应该逐字节一致（AC-FV10-087）。对应实现：`tests/test_federated_query_agent.py::test_business_table_schema_line_is_unaffected_by_a_files_value_samples`。 |

## 9. 可追溯性矩阵

| 需求 | 验收标准 | 测试用例 |
|---|---|---|
| FR-FV10-080 | AC-FV10-080, AC-FV10-081, AC-FV10-082 | TC-FV10-189, TC-FV10-190, TC-FV10-191 |
| FR-FV10-081 | AC-FV10-083, AC-FV10-084, AC-FV10-085 | TC-FV10-192, TC-FV10-193, TC-FV10-194 |
| FR-FV10-082 | AC-FV10-087 | TC-FV10-196 |
| NFR-FV10-028 | AC-FV10-085, AC-FV10-086 | TC-FV10-194, TC-FV10-195 |

## 10. 实现备注

- **AC-FV10-086 在本 Spec 最初版本被判定完成之前就被修正过了。**最初起草 AC-FV10-086 时，假设触发问题的那个场景里、`month` 列 6 个去重取值会走 `sample_range` 分支（按 AC-FV10-081），揭示出一个包含测试需要的那个精确字面量的 `'2026-01'..'2026-06'` 范围。写 TC-FV10-195 的时候，暴露出这个假设是错的：6 低于 `SAMPLE_CARDINALITY_THRESHOLD`（20），所以这一列走的是 `sample_values` 分支，而 `SAMPLE_SIZE`（5）把这份列表截断成了 `'2026-01'`..`'2026-05'`——`'2026-06'` 本身，也就是这条测试的问题真正问到的那个值，从来不会字面出现在 schema 上下文里。一条假 LLM client 只检查那个字面量在不在的测试，按最初的构想根本写不出来。假 client 的判断条件被重新设计成检查"格式有没有被揭示"（正则匹配一个类 ISO 日期的词元），而不是检查具体的字面量——模拟的是一个能从样例里归纳出格式的模型，而不是一个必须逐字看到每一个取值的模型。对着真实的 OpenAI LLM 做的实盘验证（系统设计文档第 4/6 节）证实了这个模拟符合真实行为：给到那 5 个样例，模型正确地为没有展示出来的那个取值写出了 `'2026-06'`。
- 这跟 Spec FV10.9 自己第 10 节、Spec FV10.10 自己第 10 节记录的是同一种性质的修正——一份设计拿真实情况一检查，发现需要修订——但在本项目这个模式里，是迄今为止抓得最早的一次：就发生在*写测试本身*的过程中，那条测试还从来没有针对真实代码跑过，更早于任何实盘复现。FV10.9 的修正，是在写任何代码之前，拿一份提议的设计去对照一个真实 bug 报告里的问题发现的；FV10.10 的修正，是在代码和新测试都已经写好之后，靠跑*既有*测试套件发现的；这次修正，是在试图为某一条具体测试写夹具数据时，发现背后的假设站不住脚才发现的。
- TC-FV10-189 的具体夹具（种子数据 4 条，重复一条后剩 3 个去重值）和 TC-FV10-190 的（30 个去重值），都刻意选得离 `SAMPLE_CARDINALITY_THRESHOLD` 的边界（20）远远的，正是因为 AC-FV10-086 已经在一个真正要紧的场景下，演示了*紧贴*那个边界会发生什么：这两条单元测试要确认的是"在没有歧义的情况下，走的是哪个分支"，不是去探索阈值的边界情况——那个边界情况已经被 AC-FV10-086/TC-FV10-195 顺带覆盖到了，不是刻意设计出来的。
- 实现 FR-FV10-080 需要更新两条早于本 Spec、对 `schema_json` 做逐字节相等断言的既有测试——`tests/test_structured_file_parser.py::test_schema_serializer_produces_columns_list_of_name_type_objects` 和 `tests/test_file_processing_worker.py::test_process_structured_file_produces_ready_status_schema_and_parquet_snapshot`——现在都改成预期它们那个只有一两个取值的 `VARCHAR` 列会产出 `sample_values` 键。两条都不是回归；都属于"序列化形状被刻意改变时、逐字节相等断言的测试总会需要跟着更新"这一类，跟 `SchemaSerializer.to_json()` 唯一另一个既有的调用方测试遇到的情况是同一个模式。
