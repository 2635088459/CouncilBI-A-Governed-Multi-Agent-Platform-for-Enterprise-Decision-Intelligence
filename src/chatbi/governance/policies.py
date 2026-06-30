"""Role, table, and field policies for SQL governance.

The guardrail should read like a security workflow, not like a pile of role
constants. This module keeps the access policy in one place so the guardrail
can ask one plain question: "is this role allowed to read these objects?"
"""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import UserRole
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog


_BASE_ALLOWED_TABLES_BY_ROLE: dict[UserRole, frozenset[str] | None] = {
    UserRole.BUSINESS_USER: frozenset({"orders", "revenue_by_month"}),
    UserRole.ANALYST: frozenset({"orders", "revenue_by_month", "users"}),
    UserRole.ADMIN: None,
}

_RESTRICTED_COLUMNS_BY_ROLE: dict[UserRole, frozenset[str]] = {
    UserRole.BUSINESS_USER: frozenset({"orders.user_id"}),
    UserRole.ANALYST: frozenset(),
    UserRole.ADMIN: frozenset(),
}


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """One reason a SQL query cannot pass object-level governance."""

    object_name: str
    message: str


class SqlObjectAccessPolicy:
    """Evaluate role-based table and field access for SQL guardrails."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()

    def check(
        self,
        role: UserRole,
        table_names: frozenset[str],
        field_names: frozenset[str],
    ) -> PolicyViolation | None:
        table_violation = self._check_tables(role, table_names)
        if table_violation is not None:
            return table_violation

        p0_violation = self._check_p0_fields(role, field_names)
        if p0_violation is not None:
            return p0_violation

        return self._check_role_restricted_fields(role, field_names)

    def masking_fields_for(self, field_names: frozenset[str]) -> tuple[str, ...]:
        """Return referenced P1 fields that need masking after query execution."""

        p1_fields = frozenset(self._data_model_catalog.p1_fields())
        return tuple(field_name for field_name in sorted(field_names) if field_name in p1_fields)

    def _check_tables(
        self,
        role: UserRole,
        table_names: frozenset[str],
    ) -> PolicyViolation | None:
        allowed_tables = self._allowed_tables_for_role(role)
        if allowed_tables is None:
            return None

        for table_name in sorted(table_names):
            if table_name not in allowed_tables:
                return PolicyViolation(
                    object_name=table_name,
                    message=f"Role {role.value} is not allowed to query table {table_name}.",
                )
        return None

    def _allowed_tables_for_role(self, role: UserRole) -> frozenset[str] | None:
        configured_tables = _BASE_ALLOWED_TABLES_BY_ROLE[role]
        if role is not UserRole.ANALYST or configured_tables is None:
            return configured_tables

        return frozenset(
            (
                *configured_tables,
                *self._data_model_catalog.business_table_names(),
            )
        )

    def _check_p0_fields(
        self,
        role: UserRole,
        field_names: frozenset[str],
    ) -> PolicyViolation | None:
        p0_fields = frozenset(self._data_model_catalog.p0_fields())
        for field_name in sorted(field_names):
            if field_name in p0_fields:
                return PolicyViolation(
                    object_name=field_name,
                    message=f"Role {role.value} is not allowed to query P0 field {field_name}.",
                )
        return None

    def _check_role_restricted_fields(
        self,
        role: UserRole,
        field_names: frozenset[str],
    ) -> PolicyViolation | None:
        restricted_fields = _RESTRICTED_COLUMNS_BY_ROLE[role]
        for field_name in sorted(field_names):
            if field_name in restricted_fields:
                return PolicyViolation(
                    object_name=field_name,
                    message=f"Role {role.value} is not allowed to query column {field_name}.",
                )
        return None
