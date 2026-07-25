export interface AdmissionLimits {
  maxOperations: number;
  maxWorkCenters: number;
  maxStates: number;
  maxOrders: number;
  maxSetupEntries: number;
  /** Full SDST cube |W|×|S|² must stay under this before ACL interpolation. */
  maxSetupCube: number;
  /** Exact solvers above this op count are rejected at the gateway. */
  exactSolverMaxOperations: number;
  /** ALNS/RHC-ALNS above this op count are rejected at the gateway. */
  heavyMetaheuristicMaxOperations: number;
  /** Unsized file-backed requests must stay under this byte cap. */
  maxUnslicedInstanceBytes: number;
}

export interface AdmissionIssue {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export class AdmissionError extends Error {
  readonly issues: AdmissionIssue[];

  constructor(message: string, issues: AdmissionIssue[]) {
    super(message);
    this.name = "AdmissionError";
    this.issues = issues;
  }
}

const DEFAULT_LIMITS: AdmissionLimits = {
  maxOperations: 10_000,
  maxWorkCenters: 500,
  maxStates: 200,
  maxOrders: 10_000,
  maxSetupEntries: 100_000,
  maxSetupCube: 50_000,
  exactSolverMaxOperations: 500,
  heavyMetaheuristicMaxOperations: 5_000,
  maxUnslicedInstanceBytes: 512_000,
};

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (value === undefined || value.trim().length === 0) {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.floor(parsed);
}

export function resolveAdmissionLimits(
  overrides: Partial<AdmissionLimits> = {},
  env: NodeJS.ProcessEnv = process.env,
): AdmissionLimits {
  return {
    maxOperations:
      overrides.maxOperations ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_OPERATIONS, DEFAULT_LIMITS.maxOperations),
    maxWorkCenters:
      overrides.maxWorkCenters ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_WORK_CENTERS, DEFAULT_LIMITS.maxWorkCenters),
    maxStates:
      overrides.maxStates ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_STATES, DEFAULT_LIMITS.maxStates),
    maxOrders:
      overrides.maxOrders ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_ORDERS, DEFAULT_LIMITS.maxOrders),
    maxSetupEntries:
      overrides.maxSetupEntries ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_SETUP_ENTRIES, DEFAULT_LIMITS.maxSetupEntries),
    maxSetupCube:
      overrides.maxSetupCube ??
      parsePositiveInt(env.SYNAPS_CONTROL_PLANE_MAX_SETUP_CUBE, DEFAULT_LIMITS.maxSetupCube),
    exactSolverMaxOperations:
      overrides.exactSolverMaxOperations ??
      parsePositiveInt(
        env.SYNAPS_CONTROL_PLANE_EXACT_SOLVER_MAX_OPS,
        DEFAULT_LIMITS.exactSolverMaxOperations,
      ),
    heavyMetaheuristicMaxOperations:
      overrides.heavyMetaheuristicMaxOperations ??
      parsePositiveInt(
        env.SYNAPS_CONTROL_PLANE_HEAVY_SOLVER_MAX_OPS,
        DEFAULT_LIMITS.heavyMetaheuristicMaxOperations,
      ),
    maxUnslicedInstanceBytes:
      overrides.maxUnslicedInstanceBytes ??
      parsePositiveInt(
        env.SYNAPS_CONTROL_PLANE_MAX_UNSLICED_INSTANCE_BYTES,
        DEFAULT_LIMITS.maxUnslicedInstanceBytes,
      ),
  };
}

function asObject(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function asPositiveInt(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return Math.floor(value);
}

export type SolverCostClass = "constructive" | "heavy_metaheuristic" | "exact" | "unknown";

export function classifySolverConfig(solverConfig: string | null): SolverCostClass {
  if (solverConfig === null || solverConfig.length === 0) {
    return "unknown";
  }
  const normalized = solverConfig.toUpperCase();
  if (
    normalized.startsWith("CPSAT") ||
    normalized.startsWith("LBBD") ||
    normalized === "BEAM"
  ) {
    return "exact";
  }
  if (normalized.includes("ALNS") || normalized === "RHC-ALNS") {
    return "heavy_metaheuristic";
  }
  if (
    normalized === "GREED" ||
    normalized.startsWith("RHC-GREEDY") ||
    normalized === "AUTO"
  ) {
    return "constructive";
  }
  return "unknown";
}

function reject(code: string, message: string, details?: Record<string, unknown>): never {
  throw new AdmissionError(message, [{ code, message, details }]);
}

function assertCount(
  label: string,
  code: string,
  actual: number,
  limit: number,
): void {
  if (actual > limit) {
    reject(code, `${label} count ${actual} exceeds control-plane admission limit ${limit}`, {
      actual,
      limit,
    });
  }
}

function assertSolverFitsOps(
  solverConfig: string | null,
  operationCount: number,
  limits: AdmissionLimits,
): void {
  const cost = classifySolverConfig(solverConfig);
  if (cost === "exact" && operationCount > limits.exactSolverMaxOperations) {
    reject(
      "SOLVER_OPS_ADMISSION",
      `Solver ${solverConfig} is limited to ${limits.exactSolverMaxOperations} operations on the control-plane`,
      {
        solver_config: solverConfig,
        operation_count: operationCount,
        limit: limits.exactSolverMaxOperations,
        hint: "Use GREED / RHC-GREEDY / RHC-GREEDY-COVER or lower problem size",
      },
    );
  }
  if (cost === "heavy_metaheuristic" && operationCount > limits.heavyMetaheuristicMaxOperations) {
    reject(
      "SOLVER_OPS_ADMISSION",
      `Solver ${solverConfig} is limited to ${limits.heavyMetaheuristicMaxOperations} operations on the control-plane`,
      {
        solver_config: solverConfig,
        operation_count: operationCount,
        limit: limits.heavyMetaheuristicMaxOperations,
        hint: "Use RHC-GREEDY / RHC-GREEDY-COVER for larger instances",
      },
    );
  }
  if (cost === "unknown" && operationCount > limits.maxOperations) {
    reject(
      "SOLVER_OPS_ADMISSION",
      `Unknown solver ${solverConfig} cannot exceed ${limits.maxOperations} operations`,
      { solver_config: solverConfig, operation_count: operationCount },
    );
  }
}

export function admitInlineProblem(
  problem: unknown,
  solverConfig: string | null,
  limits: AdmissionLimits,
): void {
  const normalized = asObject(problem);
  const operations = asArray(normalized.operations);
  const workCenters = asArray(normalized.work_centers);
  const states = asArray(normalized.states);
  const orders = asArray(normalized.orders);
  const setupMatrix = asArray(normalized.setup_matrix);

  assertCount("operations", "OPS_ADMISSION", operations.length, limits.maxOperations);
  assertCount("work_centers", "WORK_CENTER_ADMISSION", workCenters.length, limits.maxWorkCenters);
  assertCount("states", "STATE_ADMISSION", states.length, limits.maxStates);
  assertCount("orders", "ORDER_ADMISSION", orders.length, limits.maxOrders);
  assertCount("setup_matrix", "SETUP_ADMISSION", setupMatrix.length, limits.maxSetupEntries);

  const setupCube = workCenters.length * states.length * states.length;
  if (setupCube > limits.maxSetupCube) {
    reject(
      "SETUP_CUBE_ADMISSION",
      `Setup matrix cube |W|×|S|² = ${setupCube} exceeds limit ${limits.maxSetupCube}`,
      {
        work_centers: workCenters.length,
        states: states.length,
        setup_cube: setupCube,
        limit: limits.maxSetupCube,
      },
    );
  }

  assertSolverFitsOps(solverConfig, operations.length, limits);
}

export function admitSolvePayload(
  payload: Record<string, unknown>,
  limits: AdmissionLimits,
  options: {
    instanceFileBytes?: number | null;
  } = {},
): void {
  const solverConfig = asString(payload.solver_config);
  const problem = payload.problem;
  const instanceRef = asString(payload.problem_instance_ref);

  if (problem != null) {
    admitInlineProblem(problem, solverConfig, limits);
    return;
  }

  if (instanceRef === null) {
    reject("ADMISSION_INPUT", "Solve payload requires problem or problem_instance_ref");
  }

  const slice = asObject(payload.problem_slice);
  const maxOperations = asPositiveInt(slice.max_operations);
  const orderIds = asArray(slice.order_ids);

  if (maxOperations !== null) {
    assertCount("problem_slice.max_operations", "OPS_ADMISSION", maxOperations, limits.maxOperations);
    assertSolverFitsOps(solverConfig, maxOperations, limits);
    return;
  }

  if (orderIds.length > 0) {
    // Order-id slices still materialize unknown op counts; bound by global op cap via
    // requiring an explicit max_operations companion for control-plane safety.
    reject(
      "SLICE_ADMISSION",
      "File-backed solves with order_ids must also set problem_slice.max_operations",
      { order_ids: orderIds.length },
    );
  }

  const fileBytes = options.instanceFileBytes ?? null;
  if (fileBytes !== null && fileBytes > limits.maxUnslicedInstanceBytes) {
    reject(
      "INSTANCE_FILE_ADMISSION",
      `Unsliced problem_instance_ref is ${fileBytes} bytes; limit ${limits.maxUnslicedInstanceBytes}. ` +
        "Provide problem_slice.max_operations or raise SYNAPS_CONTROL_PLANE_MAX_UNSLICED_INSTANCE_BYTES",
      { file_bytes: fileBytes, limit: limits.maxUnslicedInstanceBytes },
    );
  }

  // Tiny unsliced files are admitted at the global op ceiling; Python still enforces model caps.
  assertSolverFitsOps(solverConfig, limits.maxOperations, limits);
}

export function admitRepairPayload(
  payload: Record<string, unknown>,
  limits: AdmissionLimits,
): void {
  const problem = payload.problem;
  if (problem == null) {
    reject("ADMISSION_INPUT", "Repair payload requires an inline problem");
  }
  admitInlineProblem(problem, "GREED", limits);

  const baseline = asObject(payload.baseline_schedule);
  const assignments = asArray(baseline.assignments);
  assertCount(
    "baseline_schedule.assignments",
    "ASSIGNMENT_ADMISSION",
    assignments.length,
    limits.maxOperations,
  );

  const disrupted = asArray(payload.disrupted_op_ids);
  assertCount(
    "disrupted_op_ids",
    "DISRUPTED_OPS_ADMISSION",
    disrupted.length,
    limits.maxOperations,
  );
}
