# 10.4 Multi-Turn Conversation Memory

## 1. Problem Solved

Today, every `POST /api/v2/chat/query` request is answered in isolation — the SQL agent, RAG agent, and file agents have no visibility into anything asked earlier in the same session. A follow-up like "and what about July?" cannot be resolved: there is nothing carrying "we were just discussing revenue" forward from the previous turn. This document designs session-scoped conversational memory, ChatGPT/Claude-style: one session is one continuous thread; starting a new session starts a fresh, unrelated conversation.

## 2. What Already Exists

`session_id` already flows through the entire stack today — every `QueryRequest`, every `QueryHistoryRecord`, every audit row carries it, and the frontend already generates one `session_id` per browser tab and reuses it for every question asked in that tab (`useRef(newSessionId()).current` in `App.tsx`). What is missing is not the identifier — it is (a) a way to *retrieve* prior turns by `session_id`, and (b) actually *using* them when generating the next answer.

## 3. Retrieving Session History

`InMemoryQueryHistory` (`src/chatbi/history/in_memory.py`) is keyed by `trace_id` only, with no session-scoped lookup. It gains:

```python
def list_by_session(self, session_id: str, *, limit: int = 5) -> tuple[QueryHistoryRecord, ...]:
    """Most recent N turns for one session, oldest first."""
```

`limit` bounds the context window — see §5 for why this must be bounded, not "the whole session."

## 4. Where Context Gets Injected

Three call sites need the prior turns, each for a different reason:

| Call site | Why it needs history | What it needs from history |
|---|---|---|
| SQL / DuckDB SQL generation (`sql_agent`, `FileDataAgent._generate_sql`, `FederatedQueryAgent._generate_sql`) | Resolve "and July?" into a complete, self-contained question before generating SQL | Prior **questions** (and ideally the resolved metric/table), not full answers |
| RAG retrieval | The retrieval query text itself needs the referent ("that" → "the July revenue drop") to find the right documents | Prior question + a short summary of what was answered |
| Answer synthesis (`GroundedAnswerSynthesizer`) | The narrated answer should read as a continuation, not repeat context the user already has | Prior question/answer pairs, verbatim or lightly truncated |

**Decided:** format the last `limit` turns as ordinary prior `{"role": "user", ...}` / `{"role": "assistant", ...}` messages and prepend them to every LLM call this pipeline already makes. There is no separate "question rewriter" step — `sql_agent`, `FileDataAgent._generate_sql`, `FederatedQueryAgent._generate_sql`, RAG retrieval, and `GroundedAnswerSynthesizer` all resolve pronoun/ellipsis references themselves, from the injected message history, exactly as a human reading the same transcript would. If real usage later shows this insufficient for some class of follow-up, that is a future revision to this decision, not a hedge carried in this document.

## 5. Context Window

Unbounded history is not viable: token cost and latency grow with every turn, and old turns are usually irrelevant to the current question. Recommendation: last **5 turns** (matching the `limit` default above), question+answer pairs only (not full evidence lists/table dumps) — this is a starting point to tune once real usage is observed, not a hard requirement.

## 6. File Stickiness Across Turns — Decided

**Decided: file attachments persist across turns within a session (Option A).** If turn 1 attaches `file_ids=[X]` and turn 2 asks a follow-up with no `file_ids`, the system reuses `X` — the user does not have to reattach the same file on every follow-up, matching the "ChatGPT-like" goal stated for this feature.

Mechanism: this is **not** implemented by scanning the bounded conversation-history window from §5 (a session could stay on the same file for far more turns than the context window keeps around). Instead, each session tracks one small piece of dedicated state — the most recently *explicitly* supplied non-empty `file_ids` for that `session_id` — independent of how much Q&A history is currently injected into LLM prompts:

- A request with a non-empty `file_ids` always uses that value, and becomes the new "active" `file_ids` for the session going forward.
- A request with an empty/omitted `file_ids` reuses the session's current active `file_ids`, if any, and is routed through the file-data branch exactly as if the client had supplied them.
- A session with no active `file_ids` yet (nothing explicitly attached this session) treats an empty request as truly fileless — no inheritance to fall back to, routes through the main orchestrator as today.
- There is intentionally no separate "detach my file" signal in this contract — the only way to stop using a file mid-session is to explicitly send a different (or empty, if the product later adds an explicit-clear affordance) `file_ids`, or start a new session (§7).

This is a real change to the routing decision in `_handle_file_data_chat_query` vs. the main orchestrator (see [FV-10](../10-user-file-upload-and-hybrid-analysis.en.md)) — the branch a request takes now depends on session state, not solely on that request's own body.

## 7. Frontend Changes

- Replace "each answer replaces the previous one" with an appended, scrolling conversation thread within the current `session_id`.
- Add a "New chat" action that generates a fresh `session_id` and clears the visible thread (the old session's history remains queryable via the existing chat-history endpoint; nothing is deleted).
- Given §6's decision, the file panel's selection state should scope to "this session" rather than "forever until manually unchecked" — when the frontend starts a new session (chat), it should also clear the visible file selection, so the UI doesn't visually suggest a file is attached to a conversation that, on the backend, no longer has any active file for the new session.

## 8. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-051 | Query history must be retrievable by `session_id`, most-recent-first, with a caller-supplied limit. | Ready to build |
| FR-FV10-052 | SQL generation, RAG retrieval, and answer synthesis must receive the last N turns of the current session as conversation context. | Ready to build |
| FR-FV10-053 | The context window size must be configurable, not hardcoded, so it can be tuned after observing real sessions. | Ready to build |
| FR-FV10-054 | The frontend must render a session as a continuous thread and provide an explicit action to start a new one. | Ready to build |
| FR-FV10-055 | An empty/omitted `file_ids` on a request inherits the session's most recently explicitly-supplied non-empty `file_ids`, if any (§6, Option A). | Ready to build |
| FR-FV10-056 | Follow-up questions are resolved purely via the message-history context from FR-FV10-052 — no separate explicit question-rewriting step (§4, Option B). | Ready to build |
