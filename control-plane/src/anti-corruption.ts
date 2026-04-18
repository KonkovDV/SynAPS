export interface AclValidationIssue {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export class AclValidationError extends Error {
  readonly issues: AclValidationIssue[];

  constructor(message: string, issues: AclValidationIssue[]) {
    super(message);
    this.name = "AclValidationError";
    this.issues = issues;
  }
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
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number") {
    return null;
  }
  return Number.isFinite(value) ? value : null;
}

function detectCycle(operations: Record<string, unknown>[]): string[] | null {
  const byId = new Map<string, Record<string, unknown>>();
  for (const operation of operations) {
    const operationId = asString(operation.id);
    if (operationId !== null) {
      byId.set(operationId, operation);
    }
  }

  const color = new Map<string, 0 | 1 | 2>();
  const stack: string[] = [];

  const visit = (nodeId: string): string[] | null => {
    color.set(nodeId, 1);
    stack.push(nodeId);

    const operation = byId.get(nodeId);
    const predecessorId = operation ? asString(operation.predecessor_op_id) : null;

    if (predecessorId !== null && byId.has(predecessorId)) {
      const predecessorColor = color.get(predecessorId) ?? 0;
      if (predecessorColor === 1) {
        const cycleStart = stack.lastIndexOf(predecessorId);
        return stack.slice(cycleStart).concat(predecessorId);
      }
      if (predecessorColor === 0) {
        const cycle = visit(predecessorId);
        if (cycle !== null) {
          return cycle;
        }
      }
    }

    stack.pop();
    color.set(nodeId, 2);
    return null;
  };

  for (const operationId of byId.keys()) {
    if ((color.get(operationId) ?? 0) !== 0) {
      continue;
    }
    const cycle = visit(operationId);
    if (cycle !== null) {
      return cycle;
    }
  }

  return null;
}

function interpolateSetupMatrix(problem: Record<string, unknown>): Record<string, unknown> {
  const workCenters = asArray(problem.work_centers).map(asObject);
  const states = asArray(problem.states).map(asObject);
  const setupMatrix = asArray(problem.setup_matrix).map(asObject);

  const stateIds = states.map((state) => asString(state.id)).filter((id): id is string => id !== null);
  const workCenterIds = workCenters
    .map((workCenter) => asString(workCenter.id))
    .filter((id): id is string => id !== null);

  if (stateIds.length === 0 || workCenterIds.length === 0) {
    return problem;
  }

  const byWorkCenter = new Map<string, number[]>();
  const existing = new Set<string>();

  for (const entry of setupMatrix) {
    const workCenterId = asString(entry.work_center_id);
    const fromStateId = asString(entry.from_state_id);
    const toStateId = asString(entry.to_state_id);
    const setupMinutes = asFiniteNumber(entry.setup_minutes);

    if (workCenterId === null || fromStateId === null || toStateId === null) {
      continue;
    }

    existing.add(`${workCenterId}:${fromStateId}:${toStateId}`);

    if (setupMinutes !== null && setupMinutes >= 0) {
      const values = byWorkCenter.get(workCenterId) ?? [];
      values.push(setupMinutes);
      byWorkCenter.set(workCenterId, values);
    }
  }

  const globalValues = Array.from(byWorkCenter.values()).flat();
  const globalAverage =
    globalValues.length > 0
      ? Math.round(globalValues.reduce((left, right) => left + right, 0) / globalValues.length)
      : 0;

  const interpolatedEntries: Record<string, unknown>[] = [];

  for (const workCenterId of workCenterIds) {
    const localValues = byWorkCenter.get(workCenterId) ?? [];
    const localAverage =
      localValues.length > 0
        ? Math.round(localValues.reduce((left, right) => left + right, 0) / localValues.length)
        : globalAverage;

    for (const fromStateId of stateIds) {
      for (const toStateId of stateIds) {
        const key = `${workCenterId}:${fromStateId}:${toStateId}`;
        if (existing.has(key)) {
          continue;
        }

        interpolatedEntries.push({
          work_center_id: workCenterId,
          from_state_id: fromStateId,
          to_state_id: toStateId,
          setup_minutes: localAverage,
          domain_attributes: {
            acl_interpolated: true,
          },
        });
      }
    }
  }

  if (interpolatedEntries.length === 0) {
    return problem;
  }

  return {
    ...problem,
    setup_matrix: [...setupMatrix, ...interpolatedEntries],
  };
}

export function applyAclGuardrails(problem: unknown): Record<string, unknown> {
  const normalizedProblem = asObject(problem);
  const operations = asArray(normalizedProblem.operations).map(asObject);

  const cycle = detectCycle(operations);
  if (cycle !== null) {
    throw new AclValidationError("Operation precedence graph contains a cycle", [
      {
        code: "PRECEDENCE_CYCLE",
        message: "Input graph is cyclic and cannot be scheduled",
        details: { cycle },
      },
    ]);
  }

  return interpolateSetupMatrix(normalizedProblem);
}
