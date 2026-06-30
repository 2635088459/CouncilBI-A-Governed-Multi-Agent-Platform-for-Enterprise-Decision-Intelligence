"""Task classification and execution planning for agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chatbi.core.contracts import AgentName


class TaskType(StrEnum):
    """V2 task types from spec/version2/02-agent-orchestration.spec.md."""

    SQL_QUERY = "sql_query"
    CHART = "chart"
    ANALYTICS = "analytics"
    RAG_EXPLANATION = "rag_explanation"
    VERIFICATION = "verification"


class ExecutionStage(StrEnum):
    """Coarse execution phases used to keep the plan easy to reason about."""

    SQL = "sql"
    FANOUT = "fanout"
    VERIFY = "verify"


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

        if self._contains_any(normalized, ("why", "reason", "cause", "explain")):
            return TaskType.RAG_EXPLANATION
        if self._contains_any(normalized, ("verify", "validate", "check answer", "audit")):
            return TaskType.VERIFICATION
        if self._contains_any(
            normalized,
            ("forecast", "predict", "prediction", "next month", "next 30 days", "anomaly", "abnormal", "outlier", "spike"),
        ):
            return TaskType.ANALYTICS
        if self._contains_any(normalized, ("chart", "plot", "visualize", "trend", "graph")):
            return TaskType.CHART
        if self._contains_any(normalized, ("revenue", "orders", "refund", "active users", "compare", "total", "count")):
            return TaskType.SQL_QUERY
        return TaskType.SQL_QUERY

    def classify_many(self, questions: tuple[str, ...]) -> tuple[TaskType, ...]:
        return tuple(self.classify(question) for question in questions)

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
        if task_type is TaskType.CHART:
            return (
                AgentPlanStep(
                    agent_name=AgentName.VISUALIZATION,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        if task_type is TaskType.ANALYTICS:
            return (
                AgentPlanStep(
                    agent_name=AgentName.ANALYTICS,
                    stage=ExecutionStage.FANOUT,
                    depends_on=(AgentName.SQL,),
                ),
            )
        if task_type is TaskType.RAG_EXPLANATION:
            return (
                AgentPlanStep(
                    agent_name=AgentName.RAG,
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
        verifier_dependencies = tuple(step.agent_name for step in fanout_steps) or (AgentName.SQL,)
        return (
            AgentPlanStep(
                agent_name=AgentName.VERIFIER,
                stage=ExecutionStage.VERIFY,
                depends_on=verifier_dependencies,
            ),
        )
