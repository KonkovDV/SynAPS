from __future__ import annotations

from pathlib import Path


DDL_DIR = Path(__file__).resolve().parents[1] / "schema" / "ddl"
CORE_DDL_PATH = DDL_DIR / "001_core_tables.sql"
AUX_DDL_PATH = DDL_DIR / "003_auxiliary_resources.sql"


def test_core_ddl_does_not_duplicate_auxiliary_tables() -> None:
    """001 must NOT define auxiliary tables — they belong in 003."""
    ddl = CORE_DDL_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS auxiliary_resources" not in ddl
    assert "CREATE TABLE IF NOT EXISTS operation_aux_requirements" not in ddl


def test_auxiliary_ddl_includes_resource_tables_before_commit() -> None:
    ddl = AUX_DDL_PATH.read_text(encoding="utf-8")

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


def test_auxiliary_ddl_has_check_constraints() -> None:
    ddl = AUX_DDL_PATH.read_text(encoding="utf-8")
    assert "CHECK (pool_size >= 1)" in ddl
    assert "CHECK (quantity_needed >= 1)" in ddl


def test_auxiliary_ddl_uses_composite_primary_key() -> None:
    """operation_aux_requirements should use composite PK, not a surrogate id."""
    ddl = AUX_DDL_PATH.read_text(encoding="utf-8")
    assert "PRIMARY KEY (operation_id, aux_resource_id)" in ddl