from chatbi.semantic.schema_drift import (
    SchemaDriftChangeType,
    SchemaDriftDetector,
    SchemaFieldSnapshot,
    SchemaSnapshot,
)


def test_schema_drift_detector_emits_added_removed_and_changed_fields() -> None:
    previous = SchemaSnapshot(
        snapshot_id="snap_001",
        semantic_version_id="sem_v1",
        fields=(
            SchemaFieldSnapshot("orders", "order_amount", "numeric", "P2"),
            SchemaFieldSnapshot("orders", "customer_id", "text", "P0"),
            SchemaFieldSnapshot("orders", "legacy_code", "text", None),
        ),
    )
    current = SchemaSnapshot(
        snapshot_id="snap_002",
        semantic_version_id="sem_v1",
        fields=(
            SchemaFieldSnapshot("orders", "order_amount", "decimal", "P2"),
            SchemaFieldSnapshot("orders", "customer_id", "text", "P1"),
            SchemaFieldSnapshot("orders", "status", "text", None),
        ),
    )

    report = SchemaDriftDetector().compare(previous, current)

    assert report.has_changes
    assert report.changed_fields == (
        "orders.status",
        "orders.legacy_code",
        "orders.customer_id",
        "orders.order_amount",
    )
    change_types = [change.change_type for change in report.changes]
    assert change_types == [
        SchemaDriftChangeType.ADDED,
        SchemaDriftChangeType.REMOVED,
        SchemaDriftChangeType.SENSITIVITY_CHANGED,
        SchemaDriftChangeType.DATA_TYPE_CHANGED,
    ]
