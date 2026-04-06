-- schema/ddl/003_auxiliary_resources.sql
-- SynAPS: Shared / auxiliary resources (PostgreSQL 17+)

BEGIN;

CREATE TABLE IF NOT EXISTS auxiliary_resources (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code              VARCHAR(80)  NOT NULL UNIQUE,
    resource_type     VARCHAR(80)  NOT NULL,
    pool_size         INTEGER      NOT NULL DEFAULT 1 CHECK (pool_size >= 1),
    domain_attributes JSONB        NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE auxiliary_resources IS
  'Shared resources required by operations (tools, fixtures, operators, clean rooms, etc.).';

CREATE TABLE IF NOT EXISTS operation_aux_requirements (
    operation_id    UUID    NOT NULL REFERENCES operations(id),
    aux_resource_id UUID    NOT NULL REFERENCES auxiliary_resources(id),
    quantity_needed INTEGER NOT NULL DEFAULT 1 CHECK (quantity_needed >= 1),
    PRIMARY KEY (operation_id, aux_resource_id)
);

COMMENT ON TABLE operation_aux_requirements IS
  'Many-to-many link: which auxiliary resources each operation requires and in what quantity.';

COMMIT;
