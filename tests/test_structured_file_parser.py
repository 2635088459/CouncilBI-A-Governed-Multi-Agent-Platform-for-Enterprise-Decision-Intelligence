import io
from pathlib import Path

import duckdb
import openpyxl
import pytest

from chatbi.files import (
    MAX_STRUCTURED_FILE_ROWS,
    ParquetWriter,
    RowLimitExceeded,
    SchemaSerializer,
    StructuredFileParser,
)


def _build_xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = openpyxl.Workbook()
    default_sheet = workbook.active
    assert default_sheet is not None
    first_title = next(iter(sheets))
    default_sheet.title = first_title
    for title, rows in sheets.items():
        worksheet = default_sheet if title == first_title else workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_csv_infers_column_names_and_types_from_a_3_column_header() -> None:
    csv_bytes = b"id,name,amount\n1,alice,10.5\n2,bob,20.25\n"

    table = StructuredFileParser().parse_csv(csv_bytes)

    assert [column.name for column in table.columns] == ["id", "name", "amount"]
    assert [column.type for column in table.columns] == ["BIGINT", "VARCHAR", "DOUBLE"]
    assert table.row_count == 2


def test_parse_xlsx_reads_first_sheet_of_a_multi_sheet_workbook() -> None:
    xlsx_bytes = _build_xlsx_bytes(
        {
            "Sheet1": [["id", "name"], [1, "alice"], [2, "bob"]],
            "Sheet2": [["unrelated"], ["data"]],
        }
    )

    table = StructuredFileParser().parse_xlsx(xlsx_bytes)

    assert [column.name for column in table.columns] == ["id", "name"]
    assert table.row_count == 2
    assert table.rows[0]["name"] == "alice"


def test_parse_raises_row_limit_exceeded_over_one_million_rows() -> None:
    header = "id\n"
    data_rows = "".join(f"{i}\n" for i in range(MAX_STRUCTURED_FILE_ROWS + 1))
    csv_bytes = (header + data_rows).encode("utf-8")

    with pytest.raises(RowLimitExceeded) as excinfo:
        StructuredFileParser().parse(csv_bytes, extension="csv")

    assert excinfo.value.row_count == MAX_STRUCTURED_FILE_ROWS + 1


def test_parse_csv_handles_quoted_commas_within_a_value() -> None:
    csv_bytes = b'id,note\n1,"hello, world"\n2,plain\n'

    table = StructuredFileParser().parse_csv(csv_bytes)

    assert table.rows[0]["note"] == "hello, world"
    assert table.rows[1]["note"] == "plain"


def test_parse_csv_handles_mixed_null_values() -> None:
    csv_bytes = b"id,name,amount\n1,alice,10.5\n2,,\n3,carol,20\n"

    table = StructuredFileParser().parse_csv(csv_bytes)

    assert table.rows[1]["name"] is None
    assert table.rows[1]["amount"] is None
    assert table.rows[0]["name"] == "alice"


def test_parquet_writer_produces_a_file_duckdb_can_scan_without_error(tmp_path: Path) -> None:
    table = StructuredFileParser().parse_csv(b"id,name\n1,alice\n2,bob\n")
    output_path = tmp_path / "snapshot.parquet"

    ParquetWriter().write(table, output_path)

    connection = duckdb.connect(":memory:")
    try:
        rows = connection.sql(f"SELECT * FROM read_parquet('{output_path}')").fetchall()
    finally:
        connection.close()
    assert rows == [(1, "alice"), (2, "bob")]


def test_schema_serializer_produces_columns_list_of_name_type_objects() -> None:
    table = StructuredFileParser().parse_csv(b"id,name\n1,alice\n")

    schema_json = SchemaSerializer().to_json(table)

    # 10-followups/11: a VARCHAR column also carries a value sample
    # (FR-FV10-080) — here a single-value sample_values list, since "alice"
    # is the column's only distinct value.
    assert schema_json == {
        "columns": [
            {"name": "id", "type": "BIGINT"},
            {"name": "name", "type": "VARCHAR", "sample_values": ["alice"]},
        ]
    }


def test_schema_serializer_adds_sample_values_for_a_low_cardinality_varchar_column() -> None:
    # TC-FV10-189 / AC-FV10-080
    csv_bytes = b"id,region\n1,US-West\n2,US-East\n3,US-West\n4,EU\n"

    table = StructuredFileParser().parse_csv(csv_bytes)
    schema_json = SchemaSerializer().to_json(table)

    region_column = next(c for c in schema_json["columns"] if c["name"] == "region")
    assert region_column["sample_values"] == ["EU", "US-East", "US-West"]
    assert "sample_range" not in region_column


def test_schema_serializer_adds_sample_range_for_a_high_cardinality_varchar_column() -> None:
    # TC-FV10-190 / AC-FV10-081
    rows = "".join(f"{i},value_{i:03d}\n" for i in range(30))
    csv_bytes = ("id,label\n" + rows).encode()

    table = StructuredFileParser().parse_csv(csv_bytes)
    schema_json = SchemaSerializer().to_json(table)

    label_column = next(c for c in schema_json["columns"] if c["name"] == "label")
    assert "sample_values" not in label_column
    assert label_column["sample_range"] == ["value_000", "value_029"]


def test_schema_serializer_never_adds_sample_keys_to_a_numeric_column() -> None:
    # TC-FV10-191 / AC-FV10-082
    csv_bytes = b"id,amount\n1,10.5\n2,20.25\n3,30.75\n"

    table = StructuredFileParser().parse_csv(csv_bytes)
    schema_json = SchemaSerializer().to_json(table)

    id_column = next(c for c in schema_json["columns"] if c["name"] == "id")
    amount_column = next(c for c in schema_json["columns"] if c["name"] == "amount")
    assert "sample_values" not in id_column and "sample_range" not in id_column
    assert "sample_values" not in amount_column and "sample_range" not in amount_column
