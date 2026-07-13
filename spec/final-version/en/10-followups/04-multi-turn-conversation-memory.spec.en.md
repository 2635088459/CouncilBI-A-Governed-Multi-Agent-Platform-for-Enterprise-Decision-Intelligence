# Spec FV10.4: Multi-Turn Conversation Memory

Source design:
- [10.4 Multi-Turn Conversation Memory design](../../../system_design/final-version/en/10-followups/04-multi-turn-conversation-memory.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; `session_id` is already part of `ChatQueryRequestV2`; this spec revises the `file_ids`-present routing branch in `_handle_file_data_chat_query`)

---

## 1. Purpose

Define session-scoped conversational context: SQL generation, RAG retrieval, and answer synthesis take the current session's recent turns into account, so a follow-up question like "and what about July?" can be answered without the user repeating context. Two behaviors flagged during initial design review as undecided have since been confirmed: file attachments persist across turns within a session (Option A), and follow-up questions are resolved purely via message history, with no separate explicit rewriting step (Option B). This spec defines both as testable requirements.

## 2. Scope

**In scope:**
- Retrieving the most recent N turns of a session's query history.
- Injecting those turns as conversation context into SQL generation, RAG retrieval, and answer synthesis.
- A configurable context-window size.
- Frontend: rendering a session as a continuous thread, with an explicit "start new session" action.
- Session-scoped `file_ids` inheritance: a request with no `file_ids` reuses the session's most recently explicitly-supplied non-empty `file_ids`.
- Resolving follow-up question references (pronouns, ellipsis) using only the conversation-history messages from FR-FV10-052 — no separate rewriting call.

**Out of scope:**
- Any change to how `session_id` is generated or its format (unchanged).
- Summarization of older turns beyond the context window (not specified; if the window proves too short in practice, that is a follow-up decision, not part of this spec).
- An explicit "detach this file from the session" action — the only ways to stop using an inherited file are to supply a different `file_ids` explicitly or start a new session.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-051 | The query history store MUST support retrieving the most recent N `QueryHistoryRecord`s for a given `session_id`, ordered oldest-to-newest, where N is caller-specified. |
| FR-FV10-052 | SQL generation (`sql_agent`, `FileDataAgent._generate_sql`, `FederatedQueryAgent._generate_sql`), RAG retrieval, and `GroundedAnswerSynthesizer` MUST receive the current session's recent turns as additional conversation context on every call. |
| FR-FV10-053 | The number of turns included (the context window) MUST be a configurable value, not a hardcoded constant, defaulting to 5. |
| FR-FV10-054 | The frontend MUST render all turns within the active `session_id` as one continuous, appended thread, and MUST provide an explicit action that starts a new `session_id` and a visually empty thread without deleting the prior session's history. |
| FR-FV10-055 | A chat query request with an empty or omitted `file_ids` MUST inherit the requesting session's most recently explicitly-supplied non-empty `file_ids`, if one exists, and MUST be routed through the file-data branch using the inherited value exactly as if the client had supplied it. A request that explicitly supplies a non-empty `file_ids` MUST use that value and MUST become the session's new inherited value for subsequent turns. A request with empty `file_ids` in a session with no prior explicit `file_ids` MUST be treated as fileless (no inheritance to fall back to). |
| FR-FV10-056 | SQL generation, RAG retrieval, and answer synthesis MUST resolve follow-up question references (pronouns, ellipsis) using only the conversation-history messages injected per FR-FV10-052. The system MUST NOT perform a separate explicit question-rewriting call before generating SQL or retrieving RAG evidence. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-018 | Adding conversation context MUST NOT increase P95 latency for a single-turn (first-question-in-session) query, since there is no history to fetch or inject in that case. |
| NFR-FV10-019 | The context window (FR-FV10-053) MUST be enforced as a hard cap — a session with more than N prior turns MUST still only inject the most recent N, never all of them. |
| NFR-FV10-020 | A session's inherited `file_ids` state (FR-FV10-055) MUST NOT be visible to or inherited by any other `session_id`, even for the same authenticated user. |

## 6. Data Contracts

### 6.1 `InMemoryQueryHistory` (extended)

```python
def list_by_session(self, session_id: str, *, limit: int = 5) -> tuple[QueryHistoryRecord, ...]:
    """Most recent `limit` turns for one session, oldest first."""
```

### 6.2 Conversation Context Shape

Turns are injected as ordinary chat messages, not a bespoke summary format:

```python
def conversation_messages(records: tuple[QueryHistoryRecord, ...]) -> tuple[dict[str, str], ...]:
    """Yields alternating {"role": "user", "content": question}, {"role": "assistant", "content": answer_text}
    for each record, oldest first, ready to prepend to an LLM call's messages tuple."""
```

### 6.3 Runtime Configuration

A new `CHATBI_CONVERSATION_CONTEXT_TURNS` environment variable (default `5`), parsed the same way other integer runtime-config values are parsed in `chatbi/core/runtime_config.py`, backs FR-FV10-053.

### 6.4 Session File Inheritance (FR-FV10-055)

A new, small store — independent of `InMemoryQueryHistory`'s bounded context window, since a session may stay on the same file for more turns than the window retains:

```python
class SessionFileContext(Protocol):
    def get_active_file_ids(self, session_id: str) -> tuple[str, ...]:
        """The most recently explicitly-supplied non-empty file_ids for this session, or () if none."""
        ...

    def set_active_file_ids(self, session_id: str, file_ids: tuple[str, ...]) -> None:
        """Record file_ids as the session's new inherited value. Only called with non-empty file_ids."""
        ...
```

Resolution helper used by `chat_query_v2` before branching into `_handle_file_data_chat_query` vs. the main orchestrator:

```python
def resolve_effective_file_ids(
    explicit_file_ids: tuple[str, ...],
    session_id: str,
    session_file_context: SessionFileContext,
) -> tuple[str, ...]:
    """FR-FV10-055: explicit file_ids always win and become the new inherited
    value; otherwise inherit the session's current value, or () if none."""
    if explicit_file_ids:
        session_file_context.set_active_file_ids(session_id, explicit_file_ids)
        return explicit_file_ids
    return session_file_context.get_active_file_ids(session_id)
```

`chat_query_v2` MUST call `resolve_effective_file_ids()` and use its return value — not the raw request body's `file_ids` — for both the routing decision (`if file_ids:`) and everything downstream (`_validate_chat_query_file_ids`, `_handle_file_data_chat_query`).

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-044 | A second question in the same session that refers back to the first question's subject (e.g. "and the month before that?") is answered correctly, using context from the first turn, without the user restating the subject. |
| AC-FV10-045 | A question asked in a **different** `session_id` by the same user does not receive any context from the first session — it is answered as if it were the only question ever asked. |
| AC-FV10-046 | A session with more than the configured context-window turns only includes the most recent window's worth of history in the next LLM call, verified by inspecting the constructed message list. |
| AC-FV10-047 | The frontend shows all turns of the current session as one continuous thread, and clicking "New chat" starts a visually empty thread while the previous session remains retrievable via the existing chat-history endpoint. |
| AC-FV10-048 | A first turn attaches `file_ids=[X]`; a second turn in the same session with empty `file_ids` is answered using file `X` (routed through the file-data branch), without the client resending `file_ids`. |
| AC-FV10-049 | A third turn in the same session as AC-FV10-048 that explicitly supplies `file_ids=[Y]` is answered using `Y`, not the inherited `X`; a fourth turn with empty `file_ids` thereafter inherits `Y`. |
| AC-FV10-050 | A first-ever question in a brand-new session, with empty `file_ids`, is answered via the main orchestrator (not the file-data branch) — there is nothing to inherit. |
| AC-FV10-051 | A follow-up question resolved via message-history context alone produces a correct answer, and the number of LLM calls made for that turn matches the number made for an equivalent first-turn question (i.e., no additional rewrite call is inserted). |

## 8. Test Plan

### 8.1 Unit Tests — Session History Retrieval

| ID | Layer | Description |
|---|---|---|
| TC-FV10-137 | unit | `list_by_session(session_id, limit=5)` returns the 5 most recent records for that session, oldest first, when 8 records exist for it. |
| TC-FV10-138 | unit | `list_by_session()` returns an empty tuple for a `session_id` with no prior records. |
| TC-FV10-139 | unit | `list_by_session()` never returns a record belonging to a different `session_id`. |

### 8.2 Unit Tests — Context Injection

| ID | Layer | Description |
|---|---|---|
| TC-FV10-140 | unit | `conversation_messages()` produces alternating user/assistant messages in chronological order for a 3-record history. |
| TC-FV10-141 | unit | An LLM call made by `sql_agent`/`FileDataAgent`/`FederatedQueryAgent` for a second-turn question includes the first turn's question/answer as leading messages. |
| TC-FV10-142 | unit | An LLM call for the **first** question in a brand-new session includes no conversation-history messages (empty history, not an error). |

### 8.3 Unit Tests — Session File Inheritance

| ID | Layer | Description |
|---|---|---|
| TC-FV10-146 | unit | `resolve_effective_file_ids(explicit=("ufile_x",), ...)` returns `("ufile_x",)` and calls `set_active_file_ids(session_id, ("ufile_x",))`. |
| TC-FV10-147 | unit | `resolve_effective_file_ids(explicit=(), ...)` for a session whose `get_active_file_ids()` returns `("ufile_x",)` returns `("ufile_x",)`. |
| TC-FV10-148 | unit | `resolve_effective_file_ids(explicit=(), ...)` for a session whose `get_active_file_ids()` returns `()` returns `()`. |
| TC-FV10-149 | unit | Calling `set_active_file_ids("ses_A", ("ufile_x",))` does not change the result of `get_active_file_ids("ses_B")` for a different session (NFR-FV10-020). |

### 8.4 Integration Tests — HTTP Multi-Turn Flow

| ID | Layer | Description |
|---|---|---|
| TC-FV10-143 | integration | Two sequential `/api/v2/chat/query` calls with the same `session_id`: the second, referencing the first's subject via pronoun, produces a correct answer (using a fixed test LLM double that asserts the expected context was present in its received prompt). |
| TC-FV10-144 | integration | The same two-question sequence run with **different** `session_id`s on the second call produces the "no context" behavior from AC-FV10-045. |
| TC-FV10-145 | integration | A session-history endpoint call after several turns reflects exactly the configured window size in a subsequent query's injected context, not the full history. |
| TC-FV10-150 | integration | Turn 1 (`file_ids=["ufile_x"]`) then turn 2 (`file_ids=[]`) in the same session: turn 2's response has `table_result_source` reflecting file/federated data, sourced from `ufile_x`, per AC-FV10-048. |
| TC-FV10-151 | integration | Turn 2 explicitly supplies `file_ids=["ufile_y"]` (different file): its response is sourced from `ufile_y`; a subsequent turn 3 with `file_ids=[]` is sourced from `ufile_y`, not `ufile_x`, per AC-FV10-049. |
| TC-FV10-152 | integration | A pronoun-referencing follow-up (AC-FV10-051) triggers exactly the same set of LLM calls (by count and call site) as a structurally equivalent first-turn question — no extra rewrite-specific call occurs. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-051 | AC-FV10-044, AC-FV10-045 | TC-FV10-137, TC-FV10-138, TC-FV10-139 |
| FR-FV10-052 | AC-FV10-044 | TC-FV10-140, TC-FV10-141, TC-FV10-143 |
| FR-FV10-053 | AC-FV10-046 | TC-FV10-145 |
| FR-FV10-054 | AC-FV10-047 | — (frontend-only; no backend test case in this spec) |
| FR-FV10-055 | AC-FV10-048, AC-FV10-049, AC-FV10-050 | TC-FV10-146, TC-FV10-147, TC-FV10-148, TC-FV10-150, TC-FV10-151 |
| FR-FV10-056 | AC-FV10-051 | TC-FV10-152 |
| NFR-FV10-018 | — | TC-FV10-142 |
| NFR-FV10-019 | AC-FV10-046 | TC-FV10-145 |
| NFR-FV10-020 | — | TC-FV10-149 |

## 10. Implementation Notes

- `resolve_effective_file_ids()` (§6.4) MUST be called once, early in `chat_query_v2`, before the existing `if file_ids:` routing branch — every downstream use of `file_ids` in that handler (validation, `_handle_file_data_chat_query`, audit logging) must use the *resolved* value, not the raw request body field, or FR-FV10-055 silently regresses to "no inheritance" for everything except the routing check itself.
- `SessionFileContext` is a new, small, session-keyed store — it is deliberately not derived by scanning `InMemoryQueryHistory.list_by_session()`, because the context window (FR-FV10-053, default 5) is unrelated to how long a file should stay "active"; a session could reference the same file for 20 turns without ever resupplying `file_ids`.
- FR-FV10-056 has no new data contract beyond §6.1/6.2 — it is a constraint on *not building something* (no rewrite function, no extra LLM call). TC-FV10-152 is the test that actually enforces this by asserting call counts, since there is no code artifact to unit-test directly for an absence.
- FR-FV10-054 (frontend thread rendering) has no backend test case because it is a pure rendering concern over data already exposed by the existing chat-history endpoint; it should be covered by frontend/E2E tests outside this backend-focused test plan's numbering, not invented here as a backend TC.
