from time import perf_counter

from chatbi.governance import GuardrailRequestV2, SimpleSqlGuardrailV2


def _p95_ms(samples: tuple[float, ...]) -> float:
    ordered = sorted(samples)
    index = int((len(ordered) - 1) * 0.95)
    return ordered[index]


def _make_request(index: int, sql_text: str) -> GuardrailRequestV2:
    return GuardrailRequestV2(
        trace_id=f"tr_guardrail_latency_{index:08d}",
        user_id="u_latency",
        role="analyst",
        sql_text=sql_text,
        semantic_version_id="sem_v1",
    )


def test_v2_guardrail_checks_1000_sql_strings_under_p95_budget() -> None:
    guardrail = SimpleSqlGuardrailV2()
    sql_fixtures = (
        "SELECT month, revenue FROM revenue_by_month",
        "SELECT month, revenue FROM revenue_by_month LIMIT 10000",
        "SELECT customers.user_email FROM customers LIMIT 25",
        "SELECT * FROM orders; DROP TABLE orders",
        "DROP TABLE orders",
    )
    requests = tuple(
        _make_request(index, sql_fixtures[index % len(sql_fixtures)])
        for index in range(1000)
    )

    samples_ms: list[float] = []
    for request in requests:
        started_at = perf_counter()
        guardrail.check(request)
        samples_ms.append((perf_counter() - started_at) * 1000)

    assert len(samples_ms) == 1000
    assert _p95_ms(tuple(samples_ms)) <= 300.0
