-- schema/ddl/001_core_tables.sql
-- Syn-APS: Core entity tables (PostgreSQL 18+)

BEGIN;

CREATE TABLE IF NOT EXISTS states (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code              VARCHAR(80)  NOT NULL UNIQUE,
    label             VARCHAR(200),
    domain_attributes JSONB        NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE states IS 'Product / process states used in SDST setup matrix and operation routing.';

CREATE TABLE IF NOT EXISTS orders (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_ref      VARCHAR(120) NOT NULL UNIQUE,
    due_date          TIMESTAMPTZ  NOT NULL,
    priority          INTEGER      NOT NULL DEFAULT 500,
    quantity          NUMERIC(12,3) NOT NULL DEFAULT 1,
    unit              VARCHAR(20)  NOT NULL DEFAULT 'pcs',
    domain_attributes JSONB        NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE orders IS 'Production / service orders to be scheduled.';

CREATE TABLE IF NOT EXISTS work_centers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code              VARCHAR(60)  NOT NULL UNIQUE,
    capability_group  VARCHAR(60)  NOT NULL,
    speed_factor      REAL         NOT NULL DEFAULT 1.0,
    max_parallel      INTEGER      NOT NULL DEFAULT 1,
    domain_attributes JSONB        NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE work_centers IS 'Machines, stations, or processing units eligible for operations.';

CREATE TABLE IF NOT EXISTS operations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id          UUID         NOT NULL REFERENCES orders(id),
    seq_in_order      INTEGER      NOT NULL,
    state_id          UUID         NOT NULL REFERENCES states(id),
    base_duration_min INTEGER      NOT NULL,
    eligible_wc_ids   JSONB        NOT NULL DEFAULT '[]',
    predecessor_op_id UUID         REFERENCES operations(id),
    domain_attributes JSONB        NOT NULL DEFAULT '{}',
    UNIQUE (order_id, seq_in_order)
);

COMMENT ON TABLE operations IS 'Individual processing steps within an order. Sequence-dependent setup times are resolved via the setup_matrix.';

COMMIT;
