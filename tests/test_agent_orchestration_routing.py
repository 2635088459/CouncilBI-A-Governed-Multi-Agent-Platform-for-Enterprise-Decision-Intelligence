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
    task_type = QuestionClassifier().classify("What was total revenue last month?")

    assert task_type is TaskType.SQL_QUERY


def test_classifier_maps_chart_question_to_chart_task() -> None:
    task_type = QuestionClassifier().classify("Show monthly revenue trend.")

    assert task_type is TaskType.CHART


def test_classifier_maps_forecast_question_to_analytics_task() -> None:
    task_type = QuestionClassifier().classify("Predict revenue for next month.")

    assert task_type is TaskType.ANALYTICS


def test_classifier_maps_why_question_to_rag_explanation_task() -> None:
    task_type = QuestionClassifier().classify("Why did revenue drop?")

    assert task_type is TaskType.RAG_EXPLANATION


def test_classifier_maps_verification_question_to_verification_task() -> None:
    task_type = QuestionClassifier().classify("Verify the answer before sending.")

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
    plan = ExecutionPlanBuilder().build(TaskType.CHART)

    assert plan.agents() == (AgentName.SQL, AgentName.VISUALIZATION, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.VISUALIZATION,)


def test_analytics_plan_routes_to_sql_analytics_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.ANALYTICS)

    assert plan.agents() == (AgentName.SQL, AgentName.ANALYTICS, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].depends_on == (AgentName.ANALYTICS,)


def test_rag_explanation_plan_routes_to_sql_rag_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.RAG_EXPLANATION)

    assert plan.agents() == (AgentName.SQL, AgentName.RAG, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.RAG,)
