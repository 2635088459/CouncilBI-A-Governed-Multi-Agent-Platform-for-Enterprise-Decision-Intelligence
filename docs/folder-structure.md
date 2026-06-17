# Folder Structure

This project uses a responsibility-based package layout. The goal is to keep each spec area easy to find and easy to test.

## Source Layout

```text
src/chatbi/
  agents/
    sql_agent.py      Agent adapters called by orchestration
  api/
    models.py          API request/response payloads and response envelope
    http.py            FastAPI adapter
  application/
    app.py             Application facade that wires API payloads to orchestration
  core/
    contracts.py       Shared domain contracts, enums, ports, and trace types
  governance/
    simple_guardrail.py SQL safety checks
  history/
    in_memory.py       Query history and replay storage
  orchestration/
    simple_orchestrator.py Request routing and workflow coordination
  semantic/
    catalog.py       Governed metric definitions and synonym resolution
```

## How To Read It

In plain terms:

- `core/` is the contract book. It defines what a request, answer, trace, warning, and guardrail result look like.
- `agents/` contains small adapters for individual agents.
- `api/` is the front door. It handles HTTP-facing shapes and the FastAPI endpoint.
- `application/` is the main switch. It connects the front door to the business workflow.
- `orchestration/` is the class monitor. It decides how a request moves through the system.
- `governance/` is the security desk. It blocks unsafe SQL before execution.
- `history/` is the notebook. It stores requests and lets us replay them by `trace_id`.
- `semantic/` is the business dictionary. It maps business words to canonical metrics.

## Test Layout

```text
tests/
  test_api_models.py
  test_app.py
  test_http_app.py
  test_in_memory_history.py
  test_overall_architecture.py
  test_simple_guardrail.py
  test_simple_orchestrator.py
```

Tests stay grouped by behavior rather than by framework. Each file should map to one small implementation area.

## Rule For New Files

Put new files where the responsibility lives:

| If you are adding... | Put it in... |
|---|---|
| individual agent adapters | `src/chatbi/agents/` |
| shared enums, dataclasses, ports | `src/chatbi/core/` |
| API payloads or HTTP routes | `src/chatbi/api/` |
| workflow wiring | `src/chatbi/application/` |
| agent routing or plans | `src/chatbi/orchestration/` |
| SQL safety, masking, policy | `src/chatbi/governance/` |
| query history, replay, audit storage | `src/chatbi/history/` |
| metric definitions, synonyms, NL2SQL helpers | `src/chatbi/semantic/` |

When a file starts needing two unrelated responsibilities, split it before it becomes hard to test.
