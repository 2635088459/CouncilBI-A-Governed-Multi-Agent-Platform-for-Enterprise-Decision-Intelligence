"""Eval case loading helpers for spec 10."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from chatbi.evaluation_repository import EvalCase


def load_eval_cases(raw_cases: Sequence[Mapping[str, object]]) -> tuple[EvalCase, ...]:
    """Load eval cases from JSON/YAML-style dictionaries."""

    cases: list[EvalCase] = []
    seen_case_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        case = _eval_case_from_mapping(raw_case, index)
        if case.case_id in seen_case_ids:
            raise ValueError(f"Duplicate eval case_id {case.case_id}.")
        seen_case_ids.add(case.case_id)
        cases.append(case)
    return tuple(cases)


def _eval_case_from_mapping(raw_case: Mapping[str, object], index: int) -> EvalCase:
    case_id = _required_string(raw_case, "case_id", index)
    question = _required_string(raw_case, "question", index)
    expected_metric_id = _optional_string(raw_case, "expected_metric_id", index)
    return EvalCase(
        case_id=case_id,
        question=question,
        expected_metric_id=expected_metric_id,
        expected_sql_fragments=_string_tuple(raw_case, "expected_sql_fragments", index),
        # FR-FV03-024/AC-FV03-021: omitting the field defaults to (),
        # reusing the same string-tuple loader as expected_sql_fragments.
        expected_chunk_ids=_string_tuple(raw_case, "expected_chunk_ids", index),
        permission_context=_permission_context(raw_case, index),
    )


def _required_string(raw_case: Mapping[str, object], field_name: str, index: int) -> str:
    value = raw_case.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Eval case {index} requires non-empty {field_name}.")
    return value.strip()


def _optional_string(
    raw_case: Mapping[str, object],
    field_name: str,
    index: int,
) -> str | None:
    value = raw_case.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Eval case {index} field {field_name} must be a string or null.")
    normalized = value.strip()
    return normalized or None


def _string_tuple(
    raw_case: Mapping[str, object],
    field_name: str,
    index: int,
) -> tuple[str, ...]:
    value = raw_case.get(field_name, ())
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"Eval case {index} field {field_name} must be a list of strings.")

    sequence_value = cast(Sequence[object], value)
    strings: list[str] = []
    for item in sequence_value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Eval case {index} field {field_name} must contain strings.")
        strings.append(item.strip())
    return tuple(strings)


def _permission_context(raw_case: Mapping[str, object], index: int) -> Mapping[str, object]:
    value = raw_case.get("permission_context", {})
    if not isinstance(value, Mapping):
        raise ValueError(f"Eval case {index} field permission_context must be an object.")
    return dict(cast(Mapping[str, object], value))
