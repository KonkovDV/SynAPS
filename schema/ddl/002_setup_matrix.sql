-- schema/ddl/002_setup_matrix.sql
-- SynAPS: Sequence-Dependent Setup Time (SDST) graph (PostgreSQL 18+)

BEGIN;

CREATE TABLE IF NOT EXISTS setup_matrix (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_center_id    UUID         NOT NULL REFERENCES work_centers(id),
    from_state_id     UUID         NOT NULL REFERENCES states(id),
    to_state_id       UUID         NOT NULL REFERENCES states(id),
    setup_minutes     INTEGER      NOT NULL,
    material_loss     NUMERIC(10,3) NOT NULL DEFAULT 0,
    energy_kwh        NUMERIC(10,3) NOT NULL DEFAULT 0,
    domain_attributes JSONB        NOT NULL DEFAULT '{}',
    UNIQUE (work_center_id, from_state_id, to_state_id)
);

COMMENT ON TABLE setup_matrix IS
  'SDST transition graph. Each row defines the changeover cost (time, material, energy) '
  'when switching from one product state to another on a specific work center.';

COMMIT;
