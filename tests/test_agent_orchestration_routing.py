from time import perf_counter

from chatbi.core.contracts import AgentName
from chatbi.orchestration.routing import (
    ExecutionPlanBuilder,
    ExecutionStage,
    QuestionClassifier,
    TaskType,
)


def _p95_ms(samples: tuple[float, ...]) -> float:
    ordered = sorted(samples)
    index = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[index]


def test_classifier_maps_plain_metric_question_to_sql_query() -> None:
    task_type = QuestionClassifier().classify_one("What was total revenue last month?")

    assert task_type is TaskType.SQL_QUERY


def test_classifier_maps_chart_question_to_chart_task() -> None:
    task_type = QuestionClassifier().classify_one("Show monthly revenue trend.")

    assert task_type is TaskType.CHART


def test_classifier_maps_forecast_question_to_analytics_task() -> None:
    task_type = QuestionClassifier().classify_one("Predict revenue for next month.")

    assert task_type is TaskType.ANALYTICS


def test_classifier_maps_why_question_to_rag_explanation_task() -> None:
    task_type = QuestionClassifier().classify_one("Why did revenue drop?")

    assert task_type is TaskType.RAG_EXPLANATION


def test_classifier_excludes_sql_for_a_pure_document_question() -> None:
    # FR-FV10-057: a RAG-matched question with no data-domain/chart/analytics
    # signal does not need SQL at all.
    types = QuestionClassifier().classify(
        "Explain what the onepager says about pricing."
    )

    assert types == frozenset({TaskType.RAG_EXPLANATION})


def test_classifier_still_includes_sql_for_a_data_grounded_explanation() -> None:
    # FR-FV10-057: "why did revenue drop" matches both a RAG keyword ("why")
    # and a data-domain keyword ("revenue") — SQL_QUERY must still be
    # present, preserving the pre-existing combined SQL+RAG behavior.
    types = QuestionClassifier().classify("Why did revenue drop?")

    assert types == frozenset({TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION})


def test_classifier_maps_verification_question_to_verification_task() -> None:
    task_type = QuestionClassifier().classify_one("Verify the answer before sending.")

    assert task_type is TaskType.VERIFICATION


def test_classifier_classifies_500_benchmark_questions_under_p95_budget() -> None:
    classifier = QuestionClassifier()
    benchmark_questions = (
        "What was total revenue last month?",
        "Show monthly revenue trend.",
        "Predict revenue for next month.",
        "Why did revenue drop?",
        "Verify the answer before sending.",
    ) * 100
    samples_ms: list[float] = []

    for question in benchmark_questions:
        started_at = perf_counter()
        classifier.classify(question)
        samples_ms.append((perf_counter() - started_at) * 1000)

    assert len(benchmark_questions) == 500
    assert _p95_ms(tuple(samples_ms)) <= 150.0


def test_classifier_classifies_many_questions_in_order() -> None:
    task_types = QuestionClassifier().classify_many(
        (
            "What was total revenue last month?",
            "Show monthly revenue trend.",
            "Predict revenue for next month.",
            "Why did revenue drop?",
            "Verify the answer before sending.",
        )
    )

    assert task_types == (
        TaskType.SQL_QUERY,
        TaskType.CHART,
        TaskType.ANALYTICS,
        TaskType.RAG_EXPLANATION,
        TaskType.VERIFICATION,
    )


def test_sql_query_plan_routes_to_sql_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.SQL_QUERY)

    assert plan.agents() == (AgentName.SQL, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.VERIFY
    assert plan.steps[1].depends_on == (AgentName.SQL,)


def test_chart_plan_routes_to_sql_visualization_and_verifier() -> None:
    # A real classify() call always pairs CHART with SQL_QUERY (charting
    # needs rows to plot), so the plan builder is exercised the same way.
    plan = ExecutionPlanBuilder().build(frozenset({TaskType.SQL_QUERY, TaskType.CHART}))

    assert plan.agents() == (AgentName.SQL, AgentName.VISUALIZATION, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.VISUALIZATION,)


def test_analytics_plan_routes_to_sql_analytics_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(frozenset({TaskType.SQL_QUERY, TaskType.ANALYTICS}))

    assert plan.agents() == (AgentName.SQL, AgentName.ANALYTICS, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].depends_on == (AgentName.ANALYTICS,)


def test_rag_explanation_plan_routes_to_sql_rag_and_verifier() -> None:
    # A data-grounded explanation ("why did revenue drop?") classifies as
    # SQL_QUERY + RAG_EXPLANATION together — RAG still gates behind SQL here.
    plan = ExecutionPlanBuilder().build(frozenset({TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION}))

    assert plan.agents() == (AgentName.SQL, AgentName.RAG, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.RAG,)


def test_rag_only_plan_skips_sql_entirely() -> None:
    # A document-only question (e.g. "Explain what the onepager says about
    # pricing") classifies as RAG_EXPLANATION alone — no SQL_QUERY — so the
    # plan has no SQL step at all and RAG runs with no dependency.
    plan = ExecutionPlanBuilder().build(frozenset({TaskType.RAG_EXPLANATION}))

    assert plan.agents() == (AgentName.RAG, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.FANOUT
    assert plan.steps[0].depends_on == ()
    assert plan.steps[1].stage is ExecutionStage.VERIFY
    assert plan.steps[1].depends_on == (AgentName.RAG,)


def test_classifier_detects_file_data_from_non_empty_file_ids_regardless_of_wording() -> None:
    # FR-FV10-016: file_ids is the decisive signal, independent of keywords.
    types = QuestionClassifier().classify(
        "What is the weather like today?", file_ids=("ufile_abc123",)
    )

    assert TaskType.FILE_DATA in types


def test_classifier_does_not_detect_file_data_without_file_ids_or_keywords() -> None:
    types = QuestionClassifier().classify("What was total revenue last month?")

    assert TaskType.FILE_DATA not in types


def test_classifier_detects_file_data_from_chinese_keywords() -> None:
    types = QuestionClassifier().classify("请把这张表和我的预测数据对比一下。")

    assert TaskType.FILE_DATA in types


def test_classifier_detects_file_data_from_english_keywords() -> None:
    types = QuestionClassifier().classify("Please compare my uploaded forecast with actuals.")

    assert TaskType.FILE_DATA in types


def test_classifier_one_prioritizes_file_data_as_the_richest_label() -> None:
    task_type = QuestionClassifier().classify_one(
        "Why did revenue drop?", file_ids=("ufile_abc123",)
    )

    assert task_type is TaskType.FILE_DATA


def test_has_data_domain_signal_true_for_the_reported_bug_question() -> None:
    # 10-followups/09: "ticket"/"total"/"count" are literal
    # _DATA_DOMAIN_KEYWORDS hits, independent of any file's schema.
    assert QuestionClassifier().has_data_domain_signal(
        "Compare total ticket count by product in H1 2026."
    )


def test_has_data_domain_signal_false_for_a_vague_question_with_no_business_vocabulary() -> None:
    assert not QuestionClassifier().has_data_domain_signal("How's it looking overall?")


def test_file_data_plan_routes_to_sql_file_data_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(frozenset({TaskType.SQL_QUERY, TaskType.FILE_DATA}))

    assert plan.agents() == (AgentName.SQL, AgentName.FILE_DATA, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.FILE_DATA,)


def test_file_data_and_rag_plan_runs_both_in_the_same_fanout_stage() -> None:
    # FR-FV10-017: FileDataAgent runs in parallel with other active agents.
    plan = ExecutionPlanBuilder().build(
        frozenset({TaskType.SQL_QUERY, TaskType.FILE_DATA, TaskType.RAG_EXPLANATION})
    )

    assert plan.agents() == (AgentName.SQL, AgentName.RAG, AgentName.FILE_DATA, AgentName.VERIFIER)
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[2].stage is ExecutionStage.FANOUT
    assert plan.steps[3].depends_on == (AgentName.RAG, AgentName.FILE_DATA)
