"""Build v2 guardrail decisions from legacy guardrail results."""

from __future__ import annotations

from chatbi.core.contracts import GuardrailDecision, GuardrailResult
from chatbi.governance.contracts import (
    GuardrailDecisionStatus,
    GuardrailDecisionV2,
)
from chatbi.governance.errors import GuardrailErrorPayloadBuilder
from chatbi.governance.masking_plan import MaskingPlanGenerator
from chatbi.governance.rule_hits import GuardrailRuleHitBuilder
from chatbi.governance.sql_hashing import SqlHasher


class GuardrailDecisionV2Builder:
    """Assemble the public v2 guardrail decision contract."""

    def __init__(
        self,
        masking_plan_generator: MaskingPlanGenerator | None = None,
        rule_hit_builder: GuardrailRuleHitBuilder | None = None,
        error_payload_builder: GuardrailErrorPayloadBuilder | None = None,
        sql_hasher: SqlHasher | None = None,
    ) -> None:
        self._masking_plan_generator = masking_plan_generator or MaskingPlanGenerator()
        self._rule_hit_builder = rule_hit_builder or GuardrailRuleHitBuilder()
        self._error_payload_builder = error_payload_builder or GuardrailErrorPayloadBuilder()
        self._sql_hasher = sql_hasher or SqlHasher()

    def build(
        self,
        sql_text: str,
        legacy_result: GuardrailResult,
    ) -> GuardrailDecisionV2:
        sql_hash = self._sql_hasher.hash(sql_text)
        if legacy_result.decision is GuardrailDecision.ALLOW:
            masking_plan = self._masking_plan_generator.generate(sql_text)
            return GuardrailDecisionV2(
                decision=GuardrailDecisionStatus.ALLOW,
                rewritten_sql=legacy_result.safe_sql,
                sql_hash=sql_hash,
                rule_hits=self._rule_hit_builder.allow_rule_hits(
                    original_sql=sql_text,
                    rewritten_sql=legacy_result.safe_sql,
                    masking_plan=masking_plan,
                ),
                masking_plan=masking_plan,
                error=None,
            )

        return GuardrailDecisionV2(
            decision=GuardrailDecisionStatus.DENY,
            rewritten_sql=None,
            sql_hash=sql_hash,
            rule_hits=self._rule_hit_builder.deny_rule_hits(
                sql_text=sql_text,
                error_code=legacy_result.error_code,
            ),
            masking_plan=[],
            error=self._error_payload_builder.build(
                error_code=legacy_result.error_code,
                message=legacy_result.message,
            ),
        )
