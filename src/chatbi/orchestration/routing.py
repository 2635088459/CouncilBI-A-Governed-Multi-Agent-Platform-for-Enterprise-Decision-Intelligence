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
    FILE_DATA = "file_data"


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


# Single source of truth for "which type wins" when a caller needs one label
# instead of the full multi-label set. Order is priority, highest first.
_TASK_TYPE_PRIORITY: tuple[TaskType, ...] = (
    TaskType.FILE_DATA,
    TaskType.RAG_EXPLANATION,
    TaskType.ANALYTICS,
    TaskType.CHART,
    TaskType.VERIFICATION,
)


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
    _VERIFICATION_KEYWORDS = (
        "verify", "double-check", "double check", "confirm", "make sure",
        "校验", "核实", "验证",
    )
    # FR-FV10-016: keywords from the design doc section 6.1, plus English
    # equivalents since the rest of this classifier's keyword sets are
    # English. The decisive signal is a non-empty `file_ids` argument to
    # classify(), not these keywords — they are the fallback text-only signal.
    _FILE_DATA_KEYWORDS = (
        "我的文件", "上传的", "这张表", "我的数据", "我的预测", "对比一下", "我的数字",
        "my file", "my uploaded", "uploaded file", "my data", "my forecast",
        "my spreadsheet", "my numbers", "this file",
    )
    # A question only needs SQL when it actually asks about queryable
    # business data. A pure document question (RAG keyword, none of these)
    # skips the SQL step entirely instead of being gated behind it.
    _DATA_DOMAIN_KEYWORDS = (
        "revenue", "order", "orders", "refund", "active users",
        "support", "ticket", "case volume", "total", "count",
        "how many", "average", "sum", "rate",
    )

    def classify(self, question: str, *, file_ids: tuple[str, ...] = ()) -> frozenset[TaskType]:
        normalized = question.strip().lower()
        types: set[TaskType] = set()

        is_rag = self._contains_any(normalized, self._RAG_KEYWORDS)
        is_analytics = self._contains_any(normalized, self._ANALYTICS_KEYWORDS)
        is_chart = self._contains_any(normalized, self._CHART_KEYWORDS)
        has_data_signal = self._contains_any(normalized, self._DATA_DOMAIN_KEYWORDS)

        # FR-FV10-016 (routing extension): a document-only question — RAG
        # keyword present, no data-domain/chart/analytics signal — does not
        # need SQL at all. Every other case still defaults to SQL, so the
        # existing "why did revenue drop" (SQL + RAG together) behavior is
        # unchanged.
        needs_sql = has_data_signal or is_chart or is_analytics or not is_rag
        if needs_sql:
            types.add(TaskType.SQL_QUERY)
        if is_rag:
            types.add(TaskType.RAG_EXPLANATION)
        if is_analytics:
            types.add(TaskType.ANALYTICS)
        if is_chart:
            types.add(TaskType.CHART)
        if self._contains_any(normalized, self._VERIFICATION_KEYWORDS):
            types.add(TaskType.VERIFICATION)
        if file_ids or self._contains_any(normalized, self._FILE_DATA_KEYWORDS):
            types.add(TaskType.FILE_DATA)

        return frozenset(types)

    def classify_one(self, question: str, *, file_ids: tuple[str, ...] = ()) -> TaskType:
        """Legacy single-label interface — returns the 'richest' type."""
        types = self.classify(question, file_ids=file_ids)
        for task_type in _TASK_TYPE_PRIORITY:
            if task_type in types:
                return task_type
        return TaskType.SQL_QUERY

    def classify_many(self, questions: tuple[str, ...]) -> tuple[TaskType, ...]:
        return tuple(self.classify_one(q) for q in questions)

    def has_data_domain_signal(self, question: str) -> bool:
        """10-followups/09: does ``question`` use business-data vocabulary
        (revenue, ticket, order, count, ...) on its own terms, independent
        of any file's schema?

        Unlike ``classify()``'s ``TaskType.SQL_QUERY`` — which defaults to
        present for almost any question via its ``or not is_rag`` fallback,
        making it a poor discriminator — this checks only the specific
        ``_DATA_DOMAIN_KEYWORDS`` hit. Used as the file-branch relevance
        gate's safety net: a token-overlap "not about your file" verdict is
        corroborated, not just assumed, when the question also independently
        reads as a real business-data question with somewhere else to go.
        """

        return self._contains_any(question.strip().lower(), self._DATA_DOMAIN_KEYWORDS)

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

        needs_sql = TaskType.SQL_QUERY in task_types
        sql_steps = (
            (AgentPlanStep(agent_name=AgentName.SQL, stage=ExecutionStage.SQL),)
            if needs_sql
            else ()
        )
        # A document-only question (RAG matched, SQL_QUERY absent) has no
        # SQL step to depend on — RAG runs standalone instead of being
        # gated behind it.
        sql_dependency: tuple[AgentName, ...] = (AgentName.SQL,) if needs_sql else ()

        fanout_steps = self._fanout_steps(task_types, sql_dependency)
        verifier_steps = self._verifier_steps(fanout_steps, sql_dependency)

        # Primary type for display: richest agent wins
        primary = TaskType.SQL_QUERY
        for task_type in _TASK_TYPE_PRIORITY:
            if task_type in task_types:
                primary = task_type
                break

        return ExecutionPlan(
            task_type=primary,
            steps=(*sql_steps, *fanout_steps, *verifier_steps),
        )

    def _fanout_steps(
        self,
        task_types: frozenset[TaskType],
        sql_dependency: tuple[AgentName, ...],
    ) -> tuple[AgentPlanStep, ...]:
        steps: list[AgentPlanStep] = []
        if TaskType.RAG_EXPLANATION in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.RAG,
                stage=ExecutionStage.FANOUT,
                depends_on=sql_dependency,
            ))
        if TaskType.CHART in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.VISUALIZATION,
                stage=ExecutionStage.FANOUT,
                depends_on=sql_dependency,
            ))
        if TaskType.ANALYTICS in task_types:
            steps.append(AgentPlanStep(
                agent_name=AgentName.ANALYTICS,
                stage=ExecutionStage.FANOUT,
                depends_on=sql_dependency,
            ))
        if TaskType.FILE_DATA in task_types:
            # FR-FV10-017: FileDataAgent runs in the same fanout stage as
            # RAG/Chart/Analytics, in parallel once SQL completes. No runner
            # is registered for AgentName.FILE_DATA yet (that needs an
            # AgentRunner adapter over FileDataAgent), so PlanExecutor will
            # skip this step gracefully — it does not raise — until that
            # adapter is wired into an orchestrator's runner map.
            steps.append(AgentPlanStep(
                agent_name=AgentName.FILE_DATA,
                stage=ExecutionStage.FANOUT,
                depends_on=sql_dependency,
            ))
        return tuple(steps)

    def _verifier_steps(
        self,
        fanout_steps: tuple[AgentPlanStep, ...],
        sql_dependency: tuple[AgentName, ...],
    ) -> tuple[AgentPlanStep, ...]:
        verifier_dependencies = tuple(step.agent_name for step in fanout_steps) or sql_dependency
        return (
            AgentPlanStep(
                agent_name=AgentName.VERIFIER,
                stage=ExecutionStage.VERIFY,
                depends_on=verifier_dependencies,
            ),
        )
