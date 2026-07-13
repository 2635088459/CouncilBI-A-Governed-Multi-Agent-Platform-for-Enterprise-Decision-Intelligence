# 10.7 Cross-Turn Value-Format Contamination in File/Federated SQL Generation

## 1. Problem Solved

A user with an active multi-turn session — a few unrelated questions already asked (ticket counts, revenue trend, etc.) — attached a structured CSV file (`regional_sales_h1_2026.csv`, `month` column formatted `"2026-01"`..`"2026-06"`) together with an unstructured note and asked a question the CSV should have answered directly. The response came back with the right column names but zero rows, and the LLM, honestly reporting what it was given, wrote "the regional sales file did not return any data" and fell back to answering from the unstructured note alone. The same question, asked as the very first message of a brand-new session with the same files, answered correctly.

That first-turn-only reproducibility ruled out the file pipeline itself — upload, parsing, Parquet snapshot, schema inference, DuckDB view registration were all confirmed working by the first-turn success. The defect was isolated by replaying the exact `FileDataAgent._generate_sql()` prompt directly against the OpenAI provider inside the running container, once with no prior turns and once with the same one unrelated prior turn the user's session actually had. With no history, the model wrote:

```sql
SELECT region, SUM(revenue) AS total_revenue, SUM(orders) AS total_orders
FROM file_ufile_adeada000b3c47dba073a99eebd9429a
GROUP BY region;
```

With the one prior turn included — a "monthly revenue trend" question answered from an unrelated business table whose narrated answer spelled months out as `"January"`, `"February"`, ... — the model wrote, deterministically, across three repeated calls at `temperature=0.0`:

```sql
SELECT region, SUM(revenue) AS total_revenue, SUM(orders) AS total_orders
FROM file_ufile_adeada000b3c47dba073a99eebd9429a
WHERE month IN ('January', 'February', 'March', 'April', 'May', 'June')
GROUP BY region;
```

Both queries are valid DuckDB SQL against the correct table with the correct column list — neither trips `find_blocked_statement()` or raises `duckdb.Error`, so neither is treated as a failure anywhere in the pipeline. The second one simply matches zero rows, because the CSV's `month` column holds `'2026-01'`..`'2026-06'`, not English month names. The model had, unprompted, carried a value format from an unrelated table in an earlier turn into a `WHERE` clause against a table that does not use that format.

This document covers the fix for that specific contamination. It does not cover — see §6 — a second, adjacent gap this investigation also surfaced: an empty-but-valid file query result is currently indistinguishable, at the HTTP layer, from "this file genuinely has no matching rows."

## 2. What Already Existed

[10.4](04-multi-turn-conversation-memory.en.md) established prior-turn injection as the sole follow-up-resolution mechanism for this codebase: no separate query-rewriting step exists anywhere in the file branch. `chat_query_v2()` (`http.py`) reads the last `conversation_context_turns` records for the session from `shared_query_history` — the same store the main orchestrator path also writes to — and passes them, verbatim, as ordinary chat messages ahead of the current question:

```python
history_turns = shared_query_history.list_by_session(
    session_id, limit=active_runtime_config.conversation_context_turns
)
api_envelope = _handle_file_data_chat_query(
    ...,
    conversation_context=conversation_messages(history_turns),
)
```

`FileDataAgent._generate_sql()` and `FederatedQueryAgent._generate_sql()` (`src/chatbi/agents/file_data_agent.py`, `src/chatbi/agents/federated_query_agent.py`) both then build the LLM request the same way:

```python
messages=(
    {"role": "system", "content": system_prompt},
    *request.conversation_context,   # prior turns, prepended verbatim
    {"role": "user", "content": request.question},
),
```

`shared_query_history` is genuinely shared: it holds every turn in the session regardless of which branch answered it — a pure-SQL orchestrator turn against `revenue_by_month`, a RAG-only turn, and a file-branch turn are all the same kind of record, with nothing in `QueryHistoryRecord` marking which agent produced it or which table it queried. This was a deliberate simplicity choice in 10.4 — one shared history store, no per-branch bookkeeping — and it is exactly what let an unrelated business-table turn's month-name formatting leak into a file query's `WHERE` clause: nothing in the pipeline distinguishes "this turn is about the same data" from "this turn happened to be recent."

`conversation_context_turns` (`RuntimeConfig`, default `5`) was, before this fix, the only knob controlling how much history reached this prompt, and it was shared by every branch that reads it.

## 3. Design: An Explicit Instruction Against Copying Literal Formats

The system prompt both agents build was silent on what to do with `conversation_context` beyond implicitly relying on the model to use it sensibly. It now says so explicitly:

```python
system_prompt = (
    "You are a DuckDB SQL generator. Reply with exactly one DuckDB "
    "SELECT statement that answers the user's question and nothing "
    "else: no explanation, no markdown code fences, no prose.\n\n"
    f"Available tables:\n{schema_context}\n\n"
    "Prior conversation turns, if present, may be about a different "
    "table or data source with different value formats (e.g. month "
    "names vs. 'YYYY-MM' strings). Use them only to resolve "
    "pronouns or follow-up references in the current question (e.g. "
    "'and July?'). Never copy a literal value or format from an "
    "earlier turn into this query — every literal must match the "
    "actual values in the tables listed above."
)
```

This is a prompt-level constraint, not a code-level guarantee — nothing here structurally prevents a model from ignoring the instruction. It is paired with §4 specifically because a prompt instruction alone is a probabilistic mitigation, and this codebase's convention (see [10.5](05-rag-only-routing-and-promotion-durability.en.md) §6, "fail loudly, don't silently under-deliver") favors also shrinking the blast radius structurally wherever a purely behavioral fix is the only lever available for the rest.

Both `FileDataAgent._generate_sql()` and `FederatedQueryAgent._generate_sql()` received the identical change — they build their system prompt the same way, from the same `build_schema_context()` helper, and had the same defect for the same reason.

## 4. Design: A Narrower, Dedicated History Window for the File Branch

`conversation_context_turns` continues to control the main orchestrator's follow-up resolution exactly as 10.4 designed it — that path's turns are far more likely to share the same underlying business tables turn-to-turn, so a wider window is lower-risk there. The file branch gets its own, separate, smaller default:

```python
# RuntimeConfig
conversation_context_turns: int = 5
file_conversation_context_turns: int = 2
```

```python
# load_runtime_config()
file_conversation_context_turns=_positive_int(
    runtime_env.get("CHATBI_FILE_CONVERSATION_CONTEXT_TURNS"), 2
),
```

```python
# http.py, chat_query_v2() — file branch only
history_turns = shared_query_history.list_by_session(
    session_id, limit=active_runtime_config.file_conversation_context_turns
)
```

The reasoning: a user's uploaded file is, by definition, not one of the org's governed business tables, so a prior turn in the same session is *more* likely — not less — to be about a differently-shaped data source than the file just attached. Without a way to tag which turns are actually about the current `file_ids` (see §6), the only structural lever available is exposure time: fewer prior turns read means fewer chances for an unrelated value format to be sitting in the prompt when SQL generation runs. This does not eliminate the failure mode — an unrelated turn asked immediately before the file question, within the window, still reaches the prompt, protected only by §3's instruction — it reduces how often that window is populated by something unrelated in the first place.

## 5. Verification

Reproduced against the running Docker stack, with a real OpenAI-backed LLM client (not the deterministic mock provider — this defect is specific to how a real model generalizes across turns, and does not reproduce against `MockLLMProvider`, which pattern-matches per-`task_type` and never sees conversation history):

- **Before the fix**, in a session with one prior unrelated turn: `table_result` came back `{"columns": ["region","total_revenue","total_orders"], "rows": []}` — reproduced deterministically 3/3 times.
- **After the fix**, rebuilding the backend/worker images and repeating the identical two-turn session: `table_result` returned both rows with correct revenue and order totals, and the synthesized answer cited them directly instead of falling back to unstructured evidence alone.
- A longer chain (four unrelated prior turns, exceeding the new two-turn window) followed by the same file question also answered correctly, confirming the narrower window did not, on its own, starve a legitimate same-session follow-up ("summarize the file" needs no pronoun resolution from prior turns at all).

`tests/test_runtime_config.py`, `tests/test_file_data_agent.py`, `tests/test_federated_query_agent.py`, `tests/test_chat_query_federated.py`, and `tests/test_v2_chat_query_http.py` were run after the change; all pass except two pre-existing, unrelated failures in `test_v2_chat_query_http.py` that require a live Postgres connection with credentials not present in this environment.

## 6. Known Limitations — Not Fixed Here

- **No relevance tagging.** `QueryHistoryRecord` still does not record which `file_ids` or which table(s) a turn actually touched. §4's fix is a blunt instrument — a smaller time window, not a relevance filter — because the data needed to build a real filter does not exist yet. A turn that *is* about the same file, asked three turns ago, is now excluded from context it could have legitimately used; a turn about something else entirely, asked one turn ago, is still included. Building an actual filter (tagging `QueryHistoryRecord` with the `file_ids`/table it used, and having the file branch only inject turns that share at least one `file_id` with the current request) is a larger change than this fix and is out of scope here.
- **A failed or empty structured query is still indistinguishable, downstream, from "the file has no matching data."** This defect happened to manifest as valid-but-empty SQL, which was never treated as an error anywhere in `_handle_file_data_chat_query` — the code path at `http.py`'s `if table_result is None and not uploaded_file_evidence:` only surfaces `structured_error_code` (e.g. `INVALID_GENERATED_SQL`) when no unstructured evidence exists to answer from instead. Whenever a request also attaches an unstructured file that does produce evidence — as the reported case did — a failed or empty structured query is silently absorbed into an evidence-only answer, with nothing in the response distinguishing "the file query genuinely found nothing" from "the file query broke and nobody was told." This investigation found and fixed the *specific* cause of one such empty result; it did not change how any empty or failed structured-query result is surfaced to the caller. That is a separate, larger design question — what should be reported, and to whom, when one branch of a multi-source answer fails but another branch still produces something — and is left for a future followup.
- **The instruction in §3 is not enforced.** A sufficiently different or more literal-minded model, or a future prompt/model change elsewhere in the same request, could still reproduce the original failure mode within the (now smaller) history window. §3 and §4 together reduce likelihood; neither is a hard guarantee.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-071 | The system prompt built by `FileDataAgent._generate_sql()` and `FederatedQueryAgent._generate_sql()` MUST instruct the model that prior conversation turns may reference a different table/data source with different value formats, that they are to be used only to resolve pronouns/follow-up references, and that every literal in the generated SQL MUST be derived from the schema of the tables listed in the same prompt, never copied from an earlier turn. | Implemented |
| FR-FV10-072 | The file branch (`chat_query_v2()`'s call into `_handle_file_data_chat_query`) MUST read session history using a dedicated `file_conversation_context_turns` limit, distinct from and independently configurable from the main orchestrator's `conversation_context_turns`, defaulting to `2`. | Implemented |
| FR-FV10-073 | `file_conversation_context_turns` MUST be configurable via the `CHATBI_FILE_CONVERSATION_CONTEXT_TURNS` environment variable, following the same non-empty/positive-integer validation and fallback-to-default behavior as `CHATBI_CONVERSATION_CONTEXT_TURNS`. | Implemented |
| NFR-FV10-024 | This change MUST NOT alter SQL-generation behavior for a file query with no prior turns in its session (empty `conversation_context`), and MUST NOT alter the main orchestrator path's use of `conversation_context_turns`. | Verified — first-turn and orchestrator-path behavior confirmed unchanged during reproduction in §5. |

## 8. Status: Fixed and Verified

Found via direct production-container reproduction rather than pre-implementation design — the same discovery mode 10.5 used for its two defects. Fixed in `src/chatbi/agents/file_data_agent.py`, `src/chatbi/agents/federated_query_agent.py`, `src/chatbi/core/runtime_config.py`, and `src/chatbi/api/http.py`; covered by new tests in `tests/test_runtime_config.py`; verified end-to-end against a rebuilt Docker image with a real LLM provider, per §5. §6's limitations were identified during the same investigation and are intentionally left for a future followup rather than folded into this fix's scope.
