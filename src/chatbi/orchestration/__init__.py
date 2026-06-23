"""Agent orchestration components."""

from typing import TYPE_CHECKING

from chatbi.orchestration.confidence import (
    CONFIDENCE_WEIGHTS,
    ConfidenceAggregationResult,
    ConfidenceAggregator,
)
from chatbi.orchestration.executor import (
    AgentRunner,
    AgentRunResult,
    AgentStepError,
    PlanExecutionResult,
    PlanExecutor,
)
from chatbi.orchestration.routing import (
    AgentPlanStep,
    ExecutionPlan,
    ExecutionPlanBuilder,
    ExecutionStage,
    QuestionClassifier,
    TaskType,
)
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog

if TYPE_CHECKING:
    from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator

__all__ = [
    "AgentPlanStep",
    "AgentRunner",
    "AgentRunResult",
    "AgentStepError",
    "AgentStepTracer",
    "CONFIDENCE_WEIGHTS",
    "ConfidenceAggregationResult",
    "ConfidenceAggregator",
    "ExecutionPlan",
    "ExecutionPlanBuilder",
    "ExecutionStage",
    "InMemoryAgentTraceLog",
    "PlanExecutionResult",
    "PlanExecutor",
    "QuestionClassifier",
    "SimpleOrchestrator",
    "TaskType",
]


def __getattr__(name: str) -> object:
    if name == "SimpleOrchestrator":
        from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator

        return SimpleOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
