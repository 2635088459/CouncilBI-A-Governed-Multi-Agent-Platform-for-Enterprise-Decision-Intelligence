"""Task classification and execution planning for agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.core.contracts import AgentName

# The TaskType support the following questions and tasks:
class TaskType(StrEnum):
    # KPI_QUERY supports questions like "What were the total sales last month?" or "Compare revenue between product A and B."
    KPI_QUERY = "kpi_query"
    # FORECAST supports questions like "What will be the sales next month?" or "Predict revenue for the next quarter."
    FORECAST = "forecast"
    # WHY_EXPLANATION supports questions like "Why did sales drop last month?" or "Explain the reason for the revenue decline."
    WHY_EXPLANATION = "why_explanation"
    # ANOMALY_DETECTION supports questions like "Detect any anomalies in sales data." or "Find outliers in revenue trends."
    ANOMALY_DETECTION = "anomaly_detection"
    # GENERAL_ANALYSIS supports questions that do not fit into the other categories.
    GENERAL_ANALYSIS = "general_analysis"

# The ExecutionStage defines the order of agent execution, ensuring SQL agents run before fanout agents, and verifiers run last.
class ExecutionStage(StrEnum):
    SQL = "sql"
    FANOUT = "fanout"
    VERIFY = "verify"

# 
@dataclass(frozen=True, slots=True)
class AgentPlanStep:
    agent_name: AgentName
    stage: ExecutionStage
    depends_on: tuple[AgentName, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    task_type: TaskType
    steps: tuple[AgentPlanStep, ...]

    def agents(self) -> tuple[AgentName, ...]:
        return tuple(step.agent_name for step in self.steps)


class QuestionClassifier:
    """Deterministic first-pass classifier for supported question types."""

    def classify(self, question: str) -> TaskType:
        normalized = question.strip().lower()

        if self._contains_any(normalized, ("forecast", "predict", "prediction", "next month", "next 30 days")):
            return TaskType.FORECAST
        if self._contains_any(normalized, ("why", "reason", "cause", "explain")):
            return TaskType.WHY_EXPLANATION
        if self._contains_any(normalized, ("anomaly", "abnormal", "outlier", "spike", "drop")):
            return TaskType.ANOMALY_DETECTION
        if self._contains_any(normalized, ("revenue", "orders", "refund", "active users", "trend", "compare")):
            return TaskType.KPI_QUERY
        return TaskType.GENERAL_ANALYSIS

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)


class ExecutionPlanBuilder:
    """Build an ordered plan that keeps SQL before fanout agents."""

    def build(self, task_type: TaskType) -> ExecutionPlan:
        sql_step = AgentPlanStep(
            agent_name=AgentName.SQL,
            stage=ExecutionStage.SQL,
        )

        fanout_steps = self._fanout_steps(task_type)
        verifier_steps = self._verifier_steps(task_type, fanout_steps)

        return ExecutionPlan(
            task_type=task_type,
            steps=(sql_step, *fanout_steps, *verifier_steps),
        )

    def _fanout_steps(self, task_type: TaskType) -> tuple[AgentPlanStep, ...]:
        if task_type is TaskType.KPI_QUERY:
            return (
                AgentPlanStep(
                    agent_name=AgentName.VISUALIZATION,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        if task_type is TaskType.FORECAST:
            return (
                AgentPlanStep(
                    agent_name=AgentName.ANALYTICS,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        if task_type is TaskType.WHY_EXPLANATION:
            return (
                AgentPlanStep(
                    agent_name=AgentName.RAG,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        if task_type is TaskType.ANOMALY_DETECTION:
            return (
                AgentPlanStep(
                    agent_name=AgentName.ANALYTICS,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        return ()

    def _verifier_steps(
        self,
        task_type: TaskType,
        fanout_steps: tuple[AgentPlanStep, ...],
    ) -> tuple[AgentPlanStep, ...]:
        if task_type is not TaskType.WHY_EXPLANATION:
            return ()
        return (
            AgentPlanStep(
                agent_name=AgentName.VERIFIER,
                stage=ExecutionStage.VERIFY,
                depends_on=tuple(step.agent_name for step in fanout_steps),
            ),
        )
