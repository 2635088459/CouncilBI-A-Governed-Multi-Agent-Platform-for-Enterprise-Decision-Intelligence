"""Masking plan generation for allowed SQL queries."""

from __future__ import annotations

from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.governance.contracts import MaskingInstruction, MaskingStrategy
from chatbi.governance.policies import SqlObjectAccessPolicy
from chatbi.governance.sql_parser import SqlReferenceParser


class MaskingPlanGenerator:
    """Create masking instructions for protected fields referenced by SQL."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._object_access_policy = SqlObjectAccessPolicy(self._data_model_catalog)
        self._reference_parser = SqlReferenceParser()

    def generate(self, sql_text: str) -> list[MaskingInstruction]:
        references = self._reference_parser.parse(sql_text)
        return [
            MaskingInstruction(
                field_name=field_name,
                strategy=MaskingStrategy.PARTIAL,
                reason="P1 field requires masking before results leave governance.",
            )
            for field_name in self._object_access_policy.masking_fields_for(
                references.field_names
            )
        ]
