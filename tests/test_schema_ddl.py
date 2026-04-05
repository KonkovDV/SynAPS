from __future__ import annotations

from pathlib import Path


DDL_PATH = Path(__file__).resolve().parents[1] / "schema" / "ddl" / "001_core_tables.sql"


def test_core_ddl_includes_auxiliary_resource_tables_before_commit() -> None:
    ddl = DDL_PATH.read_text(encoding="utf-8")

    aux_table_pos = ddl.find("CREATE TABLE IF NOT EXISTS auxiliary_resources")
    requirement_table_pos = ddl.find(
        "CREATE TABLE IF NOT EXISTS operation_aux_requirements"
    )
    commit_pos = ddl.find("COMMIT;")

    assert aux_table_pos != -1
    assert requirement_table_pos != -1
    assert commit_pos != -1
    assert aux_table_pos < requirement_table_pos < commit_pos

    ddl_before_commit = ddl[:commit_pos]
    assert "REFERENCES operations(id)" in ddl_before_commit
    assert "REFERENCES auxiliary_resources(id)" in ddl_before_commit