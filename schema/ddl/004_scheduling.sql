-- schema/ddl/004_scheduling.sql
-- SynAPS: Scheduling results, assignments, and operator overrides (PostgreSQL 17+)

BEGIN;

CREATE TABLE IF NOT EXISTS schedule_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    solver_name     VARCHAR(60)  NOT NULL,
    solver_params   JSONB        NOT NULL DEFAULT '{}',
    status          VARCHAR(20)  NOT NULL DEFAULT 'draft',
    objective_value JSONB,
    duration_ms     INTEGER,
    random_seed     BIGINT
);

COMMENT ON TABLE schedule_runs IS 'Each invocation of a solver produces one schedule run.';

CREATE TABLE IF NOT EXISTS schedule_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID        NOT NULL REFERENCES schedule_runs(id),
    operation_id    UUID        NOT NULL REFERENCES operations(id),
    work_center_id  UUID        NOT NULL REFERENCES work_centers(id),
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    setup_minutes   INTEGER     NOT NULL DEFAULT 0,
    aux_resource_ids JSONB      NOT NULL DEFAULT '[]'
);

COMMENT ON TABLE schedule_assignments IS 'Concrete operation→machine assignments with time windows.';

CREATE TABLE IF NOT EXISTS override_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id   UUID        NOT NULL REFERENCES schedule_assignments(id),
    action_type     VARCHAR(40) NOT NULL,
    operator_id     VARCHAR(120),
    reason          TEXT,
    previous_value  JSONB,
    new_value       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE override_actions IS 'Human overrides of automated schedule assignments (audit trail).';

COMMIT;
