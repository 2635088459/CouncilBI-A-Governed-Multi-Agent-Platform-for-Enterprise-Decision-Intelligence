"""Runtime settings for SQL guardrail behavior."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


DEFAULT_GUARDRAIL_MAX_ROWS = 100
DEFAULT_GUARDRAIL_TIMEOUT_MS = 30_000
GUARDRAIL_MAX_ROWS_ENV = "CHATBI_GUARDRAIL_MAX_ROWS"
GUARDRAIL_TIMEOUT_MS_ENV = "CHATBI_GUARDRAIL_TIMEOUT_MS"


@dataclass(frozen=True, slots=True)
class GuardrailSettings:
    """Configurable limits used by the SQL guardrail."""

    max_rows: int = DEFAULT_GUARDRAIL_MAX_ROWS
    timeout_ms: int = DEFAULT_GUARDRAIL_TIMEOUT_MS

    def __post_init__(self) -> None:
        if self.max_rows < 1:
            raise ValueError("max_rows must be greater than 0")
        if self.timeout_ms < 1:
            raise ValueError("timeout_ms must be greater than 0")


def load_guardrail_settings(env: Mapping[str, str] | None = None) -> GuardrailSettings:
    runtime_env = env or os.environ
    return GuardrailSettings(
        max_rows=_positive_int(
            runtime_env.get(GUARDRAIL_MAX_ROWS_ENV),
            default=DEFAULT_GUARDRAIL_MAX_ROWS,
            field_name=GUARDRAIL_MAX_ROWS_ENV,
        ),
        timeout_ms=_positive_int(
            runtime_env.get(GUARDRAIL_TIMEOUT_MS_ENV),
            default=DEFAULT_GUARDRAIL_TIMEOUT_MS,
            field_name=GUARDRAIL_TIMEOUT_MS_ENV,
        ),
    )


def _positive_int(value: str | None, default: int, field_name: str) -> int:
    if value is None or not value.strip():
        return default

    try:
        parsed_value = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc

    if parsed_value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed_value
