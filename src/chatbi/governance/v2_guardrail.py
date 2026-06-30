"""V2 adapter for the existing SQL guardrail implementation."""

from __future__ import annotations

from time import monotonic

from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.governance.audit_recorder import GuardrailDecisionAuditRecorder
from chatbi.governance.contracts import (
    GuardrailDecisionV2,
    GuardrailRequestV2,
)
from chatbi.governance.audit import GuardrailAuditLogV2
from chatbi.governance.decision_builder import GuardrailDecisionV2Builder
from chatbi.governance.legacy_adapter import GuardrailLegacyRequestAdapter
from chatbi.governance.masking_plan import MaskingPlanGenerator
from chatbi.governance.settings import GuardrailSettings
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail


class SimpleSqlGuardrailV2:
    """Expose the current guardrail through the v2 decision contract."""

    def __init__(
        self,
        guardrail: SimpleSqlGuardrail | None = None,
        audit_log: GuardrailAuditLogV2 | None = None,
        data_model_catalog: DataModelCatalog | None = None,
        settings: GuardrailSettings | None = None,
    ) -> None:
        self._guardrail = guardrail or SimpleSqlGuardrail(settings=settings)
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._decision_builder = GuardrailDecisionV2Builder(
            masking_plan_generator=MaskingPlanGenerator(self._data_model_catalog),
        )
        self._audit_recorder = GuardrailDecisionAuditRecorder(audit_log)
        self._legacy_request_adapter = GuardrailLegacyRequestAdapter()

    def check(self, request: GuardrailRequestV2) -> GuardrailDecisionV2:
        started_at = monotonic()
        legacy_result = self._guardrail.check(
            sql_text=request.sql_text,
            request=self._legacy_request_adapter.to_query_request(request),
            trace_id=request.trace_id,
        )
        decision = self._decision_builder.build(
            sql_text=request.sql_text,
            legacy_result=legacy_result,
        )
        self._audit_recorder.record(request, decision, started_at)
        return decision
