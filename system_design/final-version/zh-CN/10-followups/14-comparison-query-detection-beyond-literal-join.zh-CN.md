# 10.14 把"零行 Join 提示"的比较查询判断，扩展到字面 JOIN 语法之外

English version: [../../en/10-followups/14-comparison-query-detection-beyond-literal-join.en.md](../../en/10-followups/14-comparison-query-detection-beyond-literal-join.en.md)

## 1. 观察到的问题

[10.12](12-evidence-relevance-and-join-mismatch-caveats.zh-CN.md) 新增了 `zero_row_join_caveat`，目的就是让一次没匹配上任何数据的联邦对比，不再被叙述成一个确凿的"没有差异"结论。这个修复部署之后，一位分析师用报告里那个原始问题——"Compare my uploaded regional sales file against the revenue_by_month table in the data warehouse and flag any differences."——针对同一份 `regional_sales_h1_2026.csv` 文件重新问了一遍，得到的还是同一个错误答案：

> "There are no differences between your uploaded regional sales file and the revenue_by_month table in the data warehouse. The comparison returned zero rows, indicating that the revenue figures match for all regions and months."

这跟 10.12 本来要防止的那个错误结论一模一样。`business.revenue_by_month` 里 2026-01 到 2026-06 的种子数据是 1000、1120、1180、1210、1290、1350（`src/chatbi/migrations.py:210-217`）——比文件里每个地区每月的营收（US-West 42万~53.3万，US-East 39.8万~46.2万）低了三个数量级。文件里任何一个月的营收都不可能等于数仓那个月的汇总营收；"没有差异"对这份数据来说根本不是一个合理的真实答案——这证实了这是同一个缺陷的复现，不是巧合命中的真阴性。

## 2. 已经具备的基础

`FederatedQueryAgent._compute_zero_row_join_caveat()`（`src/chatbi/agents/federated_query_agent.py`）用的是一次字面子串匹配来决定要不要触发这道提示：

```python
if rows or "join" not in sql_text.lower():
    return False
```

一个"对比……并标出差异"这样措辞的问题，完全不要求模型必须用 `JOIN` 语法来写 SQL。被要求写一段对比逻辑时，模型经常会转而用 `EXCEPT`、`NOT EXISTS`，或者一个反连接（anti-join）子查询——这些写法里都不会出现字面的 "join" 这个词。针对这次这个具体问题，一种很可能出现的 SQL 形态是：

```sql
SELECT month FROM "file_ufile_..." EXCEPT SELECT month FROM "db_revenue_by_month"
```

两边数据源覆盖的是完全相同的六个月份（`2026-01`~`2026-06`），所以只比较 `month` 这一列——完全没有碰 `revenue`——自然会返回 0 行。这跟 10.12 设计时针对的那种"join key 不匹配"不是一回事；这其实是一个不一样、甚至可以说更糟的失败模式：生成的 SQL 实现的是一种结构上完全不同（而且在这里是错的）的"标出差异"理解方式——比较的是 key 列的集合归属关系，不是数值本身的差异——产出的结果在技术上是自洽的（这条查询确实找到了 0 行），但对回答这个问题毫无用处。因为这段 SQL 文本里没有字面的 "join"，`_compute_zero_row_join_caveat()` 最初那道门禁，在还没走到数据源行数检查之前就直接返回了 `False`，这道提示根本没机会触发。

## 3. 设计：判断"这是不是一次真正的跨数据源比较"，而不是找关键词

这道门禁被换成了真正重要的那个判断：生成的 SQL 有没有同时引用数仓表的物化视图和至少一个文件视图——不管它是靠 `JOIN`、`EXCEPT`、`NOT EXISTS`，还是 DuckDB 支持的任何其他写法：

```python
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

两个视图名都是不管有没有加引号、直接对原始 SQL 文本做子串匹配——DuckDB 要求一条查询必须真的引用它注册时用的那个确切视图名（`db_{table_name}`、`file_{file_id}`）才能跑起来，所以这道检查对模型选用哪种 join/集合运算语法是稳健的，不需要真的去解析 SQL。FR-FV10-085 原本的另外三个条件（结果为空、数仓侧数据源非空、文件侧数据源非空）保持不变。

## 4. 验证

新增的单元测试（`tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_for_an_except_comparison_with_no_literal_join_keyword`）复现了第 2 节描述的那种"只对 `month` 做 `EXCEPT`"的 SQL 形态，断言 `zero_row_join_caveat is True`。既有的单数据源测试（改名为 `test_zero_row_join_caveat_false_when_the_query_only_references_one_source`，原来是按"没有 JOIN 关键词"命名的）依然通过，只是理由变了：它只引用了 `db_revenue`，完全没引用任何文件视图，所以根本不算一次跨数据源比较。`tests/test_federated_query_agent.py` 里全部 15 个测试，以及整个项目测试套件（1397 个测试），全部通过。

这次修复还针对一次真实重新构建、重新部署的 Docker 环境、用真实的 `gpt-4o-mini` LLM client 做了端到端验证——报告那个错误答案的容器,在 10.12 落地之后没有重新构建过,这正是第一次复测依然复现了这个 bug 的原因(见第 6 节)。执行 `docker compose build backend worker && docker compose up -d --no-deps backend worker` 之后,重新上传 `regional_sales_h1_2026.csv`,通过 `POST /api/v2/chat/query` 重放报告里那个原始问题,返回的是:

> "No matching records were found across the join key(s) between your uploaded regional sales file and the revenue_by_month table in the data warehouse. This indicates that there may be a mismatch in the values or formats of the shared columns... I recommend verifying that the `month` column in both sources uses the same values and format."

`table_result.rows` 为空,`table_result_source` 是 `"federated"`——这道提示确实生效了,而且正确地塑造了这次真实模型调用给出的回答。

## 5. 已知限制——本次刻意不解决

- **这依然无法判断生成的对比 SQL 本身在语义上对不对**，只能判断一个真正为空、真正跨数据源的结果该不该带一条提示，而不是直接给出一个自信的结论。第 4 节的实盘验证就是个例子:底层那条 SQL 很可能依然是一个粗糙、甚至部分错误的对比逻辑(比如同时在 `month` 和 `revenue` 相等这两个条件上做 join，考虑到两边数值量级的巨大差异，这必然导致零匹配，而不是只在 `month` 上 join、再用一个 `revenue` 差异过滤条件)——本次修复不会让这条 SQL 变得*正确*，只是不再让系统在它什么都没算出来的时候，断言一个错误的结论。真正修好对比 SQL 本身的逻辑，是一个独立的、更难的 prompt 工程问题，本次不在范围内。
- **这道子串检查假设视图名会字面出现在查询文本里。**DuckDB 语法能表达的写法都满足这一点(要查询一个视图，就必须点它的名字)，但一种足够拐弯抹角的构造方式——比如靠字符串拼接拼出视图名、从来不以字面词元的形式出现，或者只出现在 DuckDB 在这里不支持的 `PREPARE` 语句内部——依然能绕过这道检测。目前没有观察到这类案例；这是一个理论上的缺口，本次后续调查没有找到证据证明它真的发生过。
- **10.12 文档记录的其他已知限制（该文档第 6 节）保持不变**：相关性分数下限的校准缺口，以及这道提示对"局部 join 不匹配"（部分行匹配上了、部分没匹配上）保持沉默的问题。

## 6. 顺带发现的一个部署缺口

第一次针对报告里那个问题的复测，是在 10.12 的代码修复已经落进源码树之后做的，结果依然复现了原始 bug——不是因为那时候修复本身是错的，而是因为正在运行的 Docker 容器（`backend`、`worker`）跑的是修复落地前 26 小时构建的镜像，而 `Dockerfile.backend`/`Dockerfile.worker` 是在构建时把源码 `COPY` 进镜像的，不是实时挂载的。容器必须先重新构建、重启，修复才会真正生效。这不是本项目代码或 Spec 本身的缺陷，但确实是这次调查自身验证流程里的一个真实缺口：10.7 到 10.11 都执行过的"针对重新构建的 Docker 环境做实盘验证"这一步，10.12 最初实现的时候被跳过了，而这一步本来应该能立刻发现这个部署缺口。本篇后续文档自己的第 4 节验证，在检查之前先做了重新构建和重新部署——这正是本项目自己的惯例本来就要求的流程。

## 7. 需求编号

| 编号 | 需求 | 状态 |
|---|---|---|
| FR-FV10-091 | `FederatedQueryAgent._compute_zero_row_join_caveat()` 必须通过检查生成的 SQL 文本是否同时引用了数仓表的物化视图（`db_{table_name}`）和至少一个文件视图（`file_{file_id}`），来判断这是不是一次真正的跨数据源比较——而不是靠搜索字面子串 `"join"`。 | 已实现 |

## 8. 现状：已修复并验证

通过对 10.12 本来要修复的那个原始问题做实盘复测发现——而且是在 10.12 自己的代码已经落地之后——是那次修复检测逻辑里一个真实存在的残留缺口，不是一个全新的 bug 类别。修复涉及 `src/chatbi/agents/federated_query_agent.py`；`tests/test_federated_query_agent.py` 里新增了对应测试；按第 4 节所述，在重新构建的 Docker 部署上、用真实的 OpenAI LLM client 做了验证。[Spec FV10.14](../../../../spec/final-version/zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.spec.zh-CN.md) 把这一点转化成了一条正式的功能需求，走的是跟 10.5、10.9 一样的"先实现、后补文档"顺序——这是靠实盘复现发现并修复的，不是提前设计出来的。
