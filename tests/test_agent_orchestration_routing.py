from chatbi.core.contracts import AgentName
from chatbi.orchestration.routing import (
    ExecutionPlanBuilder,
    ExecutionStage,
    QuestionClassifier,
    TaskType,
)


def test_classifier_maps_kpi_query_to_kpi_task() -> None:
    task_type = QuestionClassifier().classify("Show monthly revenue trend.")

    assert task_type is TaskType.KPI_QUERY


def test_classifier_maps_forecast_question_to_forecast_task() -> None:
    task_type = QuestionClassifier().classify("Predict revenue for next month.")

    assert task_type is TaskType.FORECAST


def test_classifier_maps_why_question_to_explanation_task() -> None:
    task_type = QuestionClassifier().classify("Why did revenue drop?")

    assert task_type is TaskType.WHY_EXPLANATION


def test_kpi_query_plan_routes_to_sql_and_visualization() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.KPI_QUERY)

    assert plan.agents() == (AgentName.SQL, AgentName.VISUALIZATION)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)


def test_forecast_plan_routes_to_sql_and_analytics() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.FORECAST)

    assert plan.agents() == (AgentName.SQL, AgentName.ANALYTICS)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].depends_on == (AgentName.SQL,)


def test_why_question_plan_routes_to_sql_rag_and_verifier() -> None:
    plan = ExecutionPlanBuilder().build(TaskType.WHY_EXPLANATION)

    assert plan.agents() == (AgentName.SQL, AgentName.RAG, AgentName.VERIFIER)
    assert plan.steps[0].stage is ExecutionStage.SQL
    assert plan.steps[1].stage is ExecutionStage.FANOUT
    assert plan.steps[1].depends_on == (AgentName.SQL,)
    assert plan.steps[2].stage is ExecutionStage.VERIFY
    assert plan.steps[2].depends_on == (AgentName.RAG,)
