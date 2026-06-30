"""Minimal SQL guardrail for the Overall Architecture workflow.

This file implements the first small, testable slice of FR-01-004:
SQL must pass through a guardrail before database execution.
"""

from __future__ import annotations

from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    GuardrailResult,
    QueryRequest,
    TableResult,
    UserRole,
)
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.governance.audit import GuardrailAuditLog
from chatbi.governance.audit_recorder import GuardrailLegacyAuditRecorder
from chatbi.governance.masking import PiiResultMasker
from chatbi.governance.policies import SqlObjectAccessPolicy
from chatbi.governance.settings import GuardrailSettings
from chatbi.governance.sql_parser import SqlReferenceParser
from chatbi.governance.sql_rewriter import RowLimitRewriter
from chatbi.governance.sql_validator import SqlStatementValidator
from chatbi.governance.timeout_policy import QueryTimeoutPolicy


_DEFAULT_ROW_LIMIT = 100
_DEFAULT_TIMEOUT_MS = 30_000


class SimpleSqlGuardrail:
    """Allow simple SELECT statements and deny dangerous SQL statements."""

    def __init__(
        self,
        default_row_limit: int = _DEFAULT_ROW_LIMIT,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        audit_log: GuardrailAuditLog | None = None,
        result_masker: PiiResultMasker | None = None,
        data_model_catalog: DataModelCatalog | None = None,
        settings: GuardrailSettings | None = None,
    ) -> None:
        active_settings = settings or GuardrailSettings(
            max_rows=default_row_limit,
            timeout_ms=timeout_ms,
        )
        self._audit_recorder = GuardrailLegacyAuditRecorder(audit_log)
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._object_access_policy = SqlObjectAccessPolicy(self._data_model_catalog)
        self._reference_parser = SqlReferenceParser()
        self._row_limit_rewriter = RowLimitRewriter(active_settings.max_rows)
        self._statement_validator = SqlStatementValidator()
        self._timeout_policy = QueryTimeoutPolicy(active_settings.timeout_ms)
        self._result_masker = result_masker or PiiResultMasker(
            data_model_catalog=self._data_model_catalog,
        )

    def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
        validation = self._statement_validator.validate(sql_text)
        if not validation.passed:
            result = self._deny(trace_id, validation.message or "SQL was denied.")
            return self._record_decision(sql_text, request, result)

        normalized_sql = validation.normalized_sql
        object_denial = self._check_object_access(normalized_sql, request.role, trace_id)
        if object_denial is not None:
            return self._record_decision(sql_text, request, object_denial)

        safe_sql = self._row_limit_rewriter.rewrite(normalized_sql).sql_text
        result = GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id=trace_id,
            safe_sql=safe_sql,
        )
        return self._record_decision(sql_text, request, result)

    def mask_result(self, table_result: TableResult) -> TableResult:
        return self._result_masker.mask(table_result)

    def check_timeout(
        self,
        elapsed_ms: int,
        sql_text: str,
        request: QueryRequest,
        trace_id: str,
    ) -> GuardrailResult | None:
        result = self._timeout_policy.check(elapsed_ms=elapsed_ms, trace_id=trace_id)
        if result is None:
            return None
        return self._record_decision(sql_text, request, result)

    def _deny(self, trace_id: str, message: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_STATEMENT,
            message=message,
        )

    def _deny_object(self, trace_id: str, message: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_OBJECT,
            message=message,
        )

    def _record_decision(
        self,
        original_sql: str,
        request: QueryRequest,
        result: GuardrailResult,
    ) -> GuardrailResult:
        return self._audit_recorder.record(original_sql, request, result)

    def _check_object_access(
        self,
        sql_text: str,
        role: UserRole,
        trace_id: str,
    ) -> GuardrailResult | None:
        references = self._reference_parser.parse(sql_text)
        violation = self._object_access_policy.check(
            role=role,
            table_names=references.table_names,
            field_names=references.field_names,
        )
        if violation is not None:
            return self._deny_object(trace_id, violation.message)
        return None
