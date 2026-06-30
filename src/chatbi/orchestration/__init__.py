"""Agent orchestration components."""

from typing import TYPE_CHECKING

from chatbi.orchestration.answer_verification import AnswerAssemblyVerifier
from chatbi.orchestration.confidence import (
    CONFIDENCE_WEIGHTS,
    ConfidenceAggregationResult,
    ConfidenceAggregator,
)
from chatbi.orchestration.contracts import (
    AgentStepInput,
    AgentStepName,
    AgentStepOutput,
    AgentStepOutputStatus,
    OrchestrationRequest,
    UserContext,
    timed_out_agent_step_output,
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
from chatbi.orchestration.state import (
    InMemoryOrchestrationStateStore,
    OrchestrationRequestState,
    OrchestrationStateStore,
    RequestStateStage,
    StoredAgentStep,
)
from chatbi.orchestration.tracing import (
    AgentStepTracer,
    AgentTraceRepository,
    InMemoryAgentTraceLog,
)
from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
    WorkerHandoffQueue,
)

if TYPE_CHECKING:
    from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator

__all__ = [
    "AgentPlanStep",
    "AgentRunner",
    "AgentRunResult",
    "AgentStepError",
    "AgentStepInput",
    "AgentStepName",
    "AgentStepOutput",
    "AgentStepOutputStatus",
    "AgentStepTracer",
    "AgentTraceRepository",
    "AnswerAssemblyVerifier",
    "AsyncTaskKind",
    "AsyncTaskRecord",
    "AsyncTaskRequest",
    "AsyncTaskStatus",
    "CONFIDENCE_WEIGHTS",
    "ConfidenceAggregationResult",
    "ConfidenceAggregator",
    "ExecutionPlan",
    "ExecutionPlanBuilder",
    "ExecutionStage",
    "InMemoryAgentTraceLog",
    "InMemoryOrchestrationStateStore",
    "InMemoryWorkerHandoffQueue",
    "OrchestrationRequest",
    "OrchestrationRequestState",
    "OrchestrationStateStore",
    "PlanExecutionResult",
    "PlanExecutor",
    "QuestionClassifier",
    "RequestStateStage",
    "SimpleOrchestrator",
    "StoredAgentStep",
    "TaskType",
    "WorkerHandoffQueue",
    "UserContext",
    "timed_out_agent_step_output",
]


def __getattr__(name: str) -> object:
    if name == "SimpleOrchestrator":
        from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator

        return SimpleOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
