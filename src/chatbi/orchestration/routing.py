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
    """Multi-label classifier: a question can need SQL + RAG + Chart simultaneously."""

    # Keywords that trigger each agent type
    _RAG_KEYWORDS = (
        "why", "reason", "cause", "explain", "what happened",
        "incident", "report", "document", "context", "background",
        "according to", "internal", "analysis says", "review",
    )
    _ANALYTICS_KEYWORDS = (
        "forecast", "predict", "prediction", "next month", "next 30 days",
        "anomaly", "abnormal", "outlier", "spike", "trajectory", "implied",
        "rate", "growth rate", "change rate", "recovery",
    )
    _CHART_KEYWORDS = (
        "chart", "plot", "visualize", "visualise", "graph",
        "trend", "bar chart", "line chart", "side by side",
    )

    def classify(self, question: str) -> frozenset[TaskType]:
        normalized = question.strip().lower()
        types: set[TaskType] = {TaskType.SQL_QUERY}

        if self._contains_any(normalized, self._RAG_KEYWORDS):
            types.add(TaskType.RAG_EXPLANATION)
        if self._contains_any(normalized, self._ANALYTICS_KEYWORDS):
            types.add(TaskType.ANALYTICS)
        if self._contains_any(normalized, self._CHART_KEYWORDS):
            types.add(TaskType.CHART)

        return frozenset(types)

    def classify_one(self, question: str) -> TaskType:
        """Legacy single-label interface — returns the 'richest' type."""
        types = self.classify(question)
        for t in (TaskType.RAG_EXPLANATION, TaskType.ANALYTICS, TaskType.CHART):
            if t in types:
                return t
        return TaskType.SQL_QUERY

    def classify_many(self, questions: tuple[str, ...]) -> tuple[TaskType, ...]:
        return tuple(self.classify_one(q) for q in questions)

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)


class ExecutionPlanBuilder:
    """Build an ordered plan that keeps SQL before fanout agents.

    Accepts a frozenset of TaskTypes so multiple fanout agents can run
    in parallel after SQL completes (e.g. RAG + Visualization together).
    """

    def build(self, task_types: frozenset[TaskType] | TaskType) -> ExecutionPlan:
        if isinstance(task_types, TaskType):
            task_types = frozenset({task_types})

        sql_step = AgentPlanStep(
            agent_name=AgentName.SQL,
            stage=ExecutionStage.SQL,
        )

        fanout_steps = self._fanout_steps(task_types)
        verifier_steps = self._verifier_steps(fanout_steps)

        # Primary type for display: richest agent wins
        primary = TaskType.SQL_QUERY
        for t in (TaskType.RAG_EXPLANATION, TaskType.ANALYTICS, TaskType.CHART):
            if t in task_types:
                primary = t
                break

        return ExecutionPlan(
            task_type=primary,
            steps=(sql_step, *fanout_steps, *verifier_steps),
        )

    def _fanout_steps(self, task_types: frozenset[TaskType]) -> tuple[AgentPlanStep, ...]:
        steps: list[AgentPlanStep] = []
        if TaskType.RAG_EXPLANATION in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.RAG,
                stage=ExecutionStage.FANOUT,
                depends_on=(AgentName.SQL,),
            ))
        if TaskType.CHART in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.VISUALIZATION,
                stage=ExecutionStage.FANOUT,
                depends_on=(AgentName.SQL,),
            ))
        if TaskType.ANALYTICS in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.ANALYTICS,
                stage=ExecutionStage.FANOUT,
                depends_on=(AgentName.SQL,),
            ))
        return tuple(steps)

    def _verifier_steps(
        self,
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
