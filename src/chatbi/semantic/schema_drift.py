"""Schema snapshot comparison for semantic governance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SchemaDriftChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    DATA_TYPE_CHANGED = "data_type_changed"
    SENSITIVITY_CHANGED = "sensitivity_changed"


@dataclass(frozen=True, slots=True)
class SchemaFieldSnapshot:
    table_name: str
    field_name: str
    data_type: str
    sensitivity: str | None = None

    @property
    def field_key(self) -> str:
        return f"{self.table_name}.{self.field_name}"


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    snapshot_id: str
    semantic_version_id: str
    fields: tuple[SchemaFieldSnapshot, ...]

    def fields_by_key(self) -> dict[str, SchemaFieldSnapshot]:
        return {field.field_key: field for field in self.fields}


@dataclass(frozen=True, slots=True)
class SchemaDriftChange:
    change_type: SchemaDriftChangeType
    field_key: str
    previous_value: str | None = None
    current_value: str | None = None


@dataclass(frozen=True, slots=True)
class SchemaDriftReport:
    previous_snapshot_id: str
    current_snapshot_id: str
    changes: tuple[SchemaDriftChange, ...]

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(change.field_key for change in self.changes)


class SchemaDriftDetector:
    """Compare two schema snapshots and emit changed fields."""

    def compare(self, previous: SchemaSnapshot, current: SchemaSnapshot) -> SchemaDriftReport:
        previous_fields = previous.fields_by_key()
        current_fields = current.fields_by_key()
        changes: list[SchemaDriftChange] = []

        for field_key in sorted(current_fields.keys() - previous_fields.keys()):
            changes.append(
                SchemaDriftChange(
                    change_type=SchemaDriftChangeType.ADDED,
                    field_key=field_key,
                    current_value=current_fields[field_key].data_type,
                )
            )
        for field_key in sorted(previous_fields.keys() - current_fields.keys()):
            changes.append(
                SchemaDriftChange(
                    change_type=SchemaDriftChangeType.REMOVED,
                    field_key=field_key,
                    previous_value=previous_fields[field_key].data_type,
                )
            )
        for field_key in sorted(previous_fields.keys() & current_fields.keys()):
            previous_field = previous_fields[field_key]
            current_field = current_fields[field_key]
            if previous_field.data_type != current_field.data_type:
                changes.append(
                    SchemaDriftChange(
                        change_type=SchemaDriftChangeType.DATA_TYPE_CHANGED,
                        field_key=field_key,
                        previous_value=previous_field.data_type,
                        current_value=current_field.data_type,
                    )
                )
            if previous_field.sensitivity != current_field.sensitivity:
                changes.append(
                    SchemaDriftChange(
                        change_type=SchemaDriftChangeType.SENSITIVITY_CHANGED,
                        field_key=field_key,
                        previous_value=previous_field.sensitivity,
                        current_value=current_field.sensitivity,
                    )
                )

        return SchemaDriftReport(
            previous_snapshot_id=previous.snapshot_id,
            current_snapshot_id=current.snapshot_id,
            changes=tuple(changes),
        )
