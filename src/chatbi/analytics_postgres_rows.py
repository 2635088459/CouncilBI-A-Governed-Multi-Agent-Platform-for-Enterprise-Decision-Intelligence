"""PostgreSQL row mapping for analytics v2 results.

Keep this file database-driver free. It only knows two things: the analytics
table shape, and how to translate typed Python records to/from row mappings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from chatbi.analytics import (
    AnomalyPoint,
    AnalyticsRecord,
    AnalyticsResult,
    ForecastPoint,
)


ANALYTICS_V2_TABLES_SQL = """
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.results (
    trace_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL DEFAULT 'org_legacy',
    user_id TEXT NOT NULL DEFAULT 'user_legacy',
    metric_id TEXT NOT NULL,
    semantic_version_id TEXT NOT NULL,
    parameters JSONB NOT NULL,
    anomaly_points JSONB NOT NULL,
    forecast_points JSONB NOT NULL,
    confidence_interval JSONB,
    quality_warnings TEXT[] NOT NULL DEFAULT '{}',
    method TEXT NOT NULL,
    model_version TEXT NOT NULL,
    explanation TEXT NOT NULL
);

ALTER TABLE analytics.results
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_legacy';

ALTER TABLE analytics.results
    ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'user_legacy';

CREATE INDEX IF NOT EXISTS idx_analytics_results_metric_id
    ON analytics.results(metric_id);

CREATE INDEX IF NOT EXISTS idx_analytics_results_semantic_version_id
    ON analytics.results(semantic_version_id);

CREATE INDEX IF NOT EXISTS idx_analytics_results_org_trace_id
    ON analytics.results(org_id, trace_id);

CREATE INDEX IF NOT EXISTS idx_analytics_results_org_user_trace_id
    ON analytics.results(org_id, user_id, trace_id);
""".strip()


def analytics_record_to_row(record: AnalyticsRecord) -> Mapping[str, object | None]:
    return {
        "trace_id": record.trace_id,
        "org_id": record.org_id,
        "user_id": record.user_id,
        "metric_id": record.metric_id,
        "semantic_version_id": record.semantic_version_id,
        "parameters": dict(record.parameters),
        "anomaly_points": tuple(_anomaly_point_to_json(point) for point in record.result.anomaly_points),
        "forecast_points": tuple(_forecast_point_to_json(point) for point in record.result.forecast_points),
        "confidence_interval": (
            dict(record.result.confidence_interval)
            if record.result.confidence_interval is not None
            else None
        ),
        "quality_warnings": record.result.quality_warnings,
        "method": record.result.method,
        "model_version": record.result.model_version,
        "explanation": record.result.explanation,
    }


def analytics_record_from_row(row: Mapping[str, object]) -> AnalyticsRecord:
    result = AnalyticsResult(
        anomaly_points=tuple(
            anomaly_point_from_json(point)
            for point in _json_sequence(row, "anomaly_points")
        ),
        forecast_points=tuple(
            forecast_point_from_json(point)
            for point in _json_sequence(row, "forecast_points")
        ),
        confidence_interval=_optional_float_mapping(row, "confidence_interval"),
        quality_warnings=_string_tuple(row, "quality_warnings"),
        method=_string(row, "method"),
        model_version=_string(row, "model_version"),
        explanation=_string(row, "explanation"),
    )
    return AnalyticsRecord(
        trace_id=_string(row, "trace_id"),
        metric_id=_string(row, "metric_id"),
        semantic_version_id=_string(row, "semantic_version_id"),
        parameters=_object_mapping(row, "parameters"),
        result=result,
        org_id=_optional_string(row, "org_id", default="org_legacy"),
        user_id=_optional_string(row, "user_id", default="user_legacy"),
    )


def anomaly_point_from_json(value: object) -> AnomalyPoint:
    row = _mapping(value, "anomaly_point")
    return AnomalyPoint(
        index=_integer(row, "index"),
        timestamp=_string(row, "timestamp"),
        value=_float(row, "value"),
        score=_float(row, "score"),
        method=_string(row, "method"),
    )


def forecast_point_from_json(value: object) -> ForecastPoint:
    row = _mapping(value, "forecast_point")
    return ForecastPoint(
        timestamp=_string(row, "timestamp"),
        value=_float(row, "value"),
        lower=_float(row, "lower"),
        upper=_float(row, "upper"),
    )


def _anomaly_point_to_json(point: AnomalyPoint) -> Mapping[str, object]:
    return {
        "index": point.index,
        "timestamp": point.timestamp,
        "value": point.value,
        "score": point.score,
        "method": point.method,
    }


def _forecast_point_to_json(point: ForecastPoint) -> Mapping[str, object]:
    return {
        "timestamp": point.timestamp,
        "value": point.value,
        "lower": point.lower,
        "upper": point.upper,
    }


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return cast(Mapping[str, object], value)


def _object_mapping(row: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    value = row.get(field_name)
    return _mapping(value, field_name)


def _optional_float_mapping(
    row: Mapping[str, object],
    field_name: str,
) -> Mapping[str, float] | None:
    value = row.get(field_name)
    if value is None:
        return None
    mapping = _mapping(value, field_name)
    return {key: _float(mapping, key) for key in mapping}


def _json_sequence(row: Mapping[str, object], field_name: str) -> tuple[object, ...]:
    value = row.get(field_name)
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence")
    return tuple(cast(Sequence[object], value))


def _string_tuple(row: Mapping[str, object], field_name: str) -> tuple[str, ...]:
    value = row.get(field_name)
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence of strings")
    values = tuple(cast(Sequence[object], value))
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{field_name} must be a sequence of strings")
    return cast(tuple[str, ...], values)


def _string(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(row: Mapping[str, object], field_name: str, *, default: str) -> str:
    if field_name not in row:
        return default
    return _string(row, field_name)


def _integer(row: Mapping[str, object], field_name: str) -> int:
    value = row.get(field_name)
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _float(row: Mapping[str, object], field_name: str) -> float:
    value = row.get(field_name)
    if not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)
