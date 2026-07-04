"""In-memory LLM cost ledger used by tests and local runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from chatbi.core.contracts import utc_now
from chatbi.llm.types import LLMRequest, LLMResponse


def _empty_records() -> list["LLMCostRecord"]:
    return []


@dataclass(frozen=True, slots=True)
class LLMCostRecord:
    user_id: str
    org_id: str
    task_type: str
    day: date
    total_tokens: int
    estimated_cost: float


@dataclass(slots=True)
class InMemoryLLMCostStore:
    _records: list[LLMCostRecord] = field(default_factory=_empty_records)

    def record(self, request: LLMRequest, response: LLMResponse) -> None:
        self._records.append(
            LLMCostRecord(
                user_id=request.user_id,
                org_id=request.org_id,
                task_type=request.task_type,
                day=utc_now().date(),
                total_tokens=response.total_tokens,
                estimated_cost=response.estimated_cost,
            )
        )

    def aggregate(
        self,
        *,
        user_id: str | None = None,
        org_id: str | None = None,
        task_type: str | None = None,
        day: date | None = None,
    ) -> LLMCostRecord:
        matched = [
            record
            for record in self._records
            if (user_id is None or record.user_id == user_id)
            and (org_id is None or record.org_id == org_id)
            and (task_type is None or record.task_type == task_type)
            and (day is None or record.day == day)
        ]
        return LLMCostRecord(
            user_id=user_id or "*",
            org_id=org_id or "*",
            task_type=task_type or "*",
            day=day or utc_now().date(),
            total_tokens=sum(record.total_tokens for record in matched),
            estimated_cost=round(sum(record.estimated_cost for record in matched), 8),
        )

    def list_records(self) -> tuple[LLMCostRecord, ...]:
        return tuple(self._records)
