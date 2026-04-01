-- schema/ddl/005_indexes.sql
-- Syn-APS: Secondary indexes for common query patterns (PostgreSQL 18+)

BEGIN;

-- Operations
CREATE INDEX IF NOT EXISTS idx_operations_order       ON operations (order_id);
CREATE INDEX IF NOT EXISTS idx_operations_state       ON operations (state_id);
CREATE INDEX IF NOT EXISTS idx_operations_predecessor ON operations (predecessor_op_id);

-- Setup matrix
CREATE INDEX IF NOT EXISTS idx_setup_wc_from_to ON setup_matrix (work_center_id, from_state_id, to_state_id);
CREATE INDEX IF NOT EXISTS idx_setup_wc         ON setup_matrix (work_center_id);

-- Auxiliary resources
CREATE INDEX IF NOT EXISTS idx_aux_req_operation ON operation_aux_requirements (operation_id);
CREATE INDEX IF NOT EXISTS idx_aux_req_resource  ON operation_aux_requirements (aux_resource_id);

-- Schedule assignments
CREATE INDEX IF NOT EXISTS idx_assignments_run       ON schedule_assignments (run_id);
CREATE INDEX IF NOT EXISTS idx_assignments_operation ON schedule_assignments (operation_id);
CREATE INDEX IF NOT EXISTS idx_assignments_wc        ON schedule_assignments (work_center_id);
CREATE INDEX IF NOT EXISTS idx_assignments_time      ON schedule_assignments (start_time, end_time);

-- Override actions
CREATE INDEX IF NOT EXISTS idx_overrides_assignment ON override_actions (assignment_id);

COMMIT;
