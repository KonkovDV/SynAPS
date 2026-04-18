type AnyObject = Record<string, unknown>;

interface UiOrder {
  id: string;
  due_date: string;
}

interface UiOperation {
  id: string;
  order_id: string;
  predecessor_op_id: string | null;
  base_duration_min: number;
}

interface UiWorkCenter {
  id: string;
  code: string;
}

interface UiAssignment {
  operation_id: string;
  work_center_id: string;
  start_time: string;
  end_time: string;
}

export interface BuildGanttModelRequest {
  problem: AnyObject;
  schedule: {
    assignments: AnyObject[];
  };
  baseline_schedule?: {
    assignments: AnyObject[];
  };
}

function asObject(value: unknown): AnyObject {
  return typeof value === "object" && value !== null ? (value as AnyObject) : {};
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

function parseIsoDate(value: string | null): number | null {
  if (value === null) {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function computeDuePressure(slackMinutes: number, pBar: number): number {
  if (slackMinutes <= 0) {
    return 1.0;
  }
  return Math.exp(-slackMinutes / Math.max(pBar, 1.0));
}

function pressureColor(slackMinutes: number, pBar: number): string {
  if (slackMinutes <= 0) {
    return "#d73027";
  }
  if (slackMinutes <= pBar) {
    return "#fdae61";
  }
  return "#1a9850";
}

export function buildGanttModel(input: BuildGanttModelRequest): AnyObject {
  const problem = asObject(input.problem);

  const orders: UiOrder[] = asArray(problem.orders)
    .map(asObject)
    .flatMap((order): UiOrder[] => {
      const orderId = asString(order.id);
      const dueDate = asString(order.due_date);
      if (orderId === null || dueDate === null) {
        return [];
      }
      return [{ id: orderId, due_date: dueDate }];
    });

  const operations: UiOperation[] = asArray(problem.operations)
    .map(asObject)
    .flatMap((operation): UiOperation[] => {
      const operationId = asString(operation.id);
      const orderId = asString(operation.order_id);
      const predecessor = asString(operation.predecessor_op_id);
      const duration = asFiniteNumber(operation.base_duration_min);
      if (operationId === null || orderId === null || duration === null) {
        return [];
      }
      return [
        {
          id: operationId,
          order_id: orderId,
          predecessor_op_id: predecessor,
          base_duration_min: duration,
        },
      ];
    });

  const workCenters: UiWorkCenter[] = asArray(problem.work_centers)
    .map(asObject)
    .flatMap((workCenter): UiWorkCenter[] => {
      const workCenterId = asString(workCenter.id);
      if (workCenterId === null) {
        return [];
      }
      return [
        {
          id: workCenterId,
          code: asString(workCenter.code) ?? workCenterId,
        },
      ];
    });

  const assignments: UiAssignment[] = asArray(asObject(input.schedule).assignments)
    .map(asObject)
    .flatMap((assignment): UiAssignment[] => {
      const operationId = asString(assignment.operation_id);
      const workCenterId = asString(assignment.work_center_id);
      const startTime = asString(assignment.start_time);
      const endTime = asString(assignment.end_time);
      if (
        operationId === null ||
        workCenterId === null ||
        startTime === null ||
        endTime === null
      ) {
        return [];
      }
      return [
        {
          operation_id: operationId,
          work_center_id: workCenterId,
          start_time: startTime,
          end_time: endTime,
        },
      ];
    });

  const baselineAssignments = asArray(asObject(input.baseline_schedule).assignments)
    .map(asObject)
    .flatMap((assignment): UiAssignment[] => {
      const operationId = asString(assignment.operation_id);
      const workCenterId = asString(assignment.work_center_id);
      const startTime = asString(assignment.start_time);
      const endTime = asString(assignment.end_time);
      if (
        operationId === null ||
        workCenterId === null ||
        startTime === null ||
        endTime === null
      ) {
        return [];
      }
      return [
        {
          operation_id: operationId,
          work_center_id: workCenterId,
          start_time: startTime,
          end_time: endTime,
        },
      ];
    });

  const ordersById = new Map(orders.map((order) => [order.id, order]));
  const operationsById = new Map(operations.map((operation) => [operation.id, operation]));
  const baselineByOperationId = new Map(
    baselineAssignments.map((assignment) => [assignment.operation_id, assignment]),
  );

  const pBar =
    operations.length > 0
      ? operations.reduce((sum, operation) => sum + operation.base_duration_min, 0) /
        operations.length
      : 1.0;

  const lanesByWorkCenter = new Map(
    workCenters.map((workCenter) => [workCenter.id, { ...workCenter, bars: [] as AnyObject[] }]),
  );
  const deltas: AnyObject[] = [];

  for (const assignment of assignments) {
    const operation = operationsById.get(assignment.operation_id);
    const order = operation ? ordersById.get(operation.order_id) : undefined;

    const endMs = parseIsoDate(assignment.end_time);
    const dueMs = parseIsoDate(order?.due_date ?? null);

    let slackMinutes = 0;
    if (endMs !== null && dueMs !== null) {
      slackMinutes = (dueMs - endMs) / 60000.0;
    }

    const duePressure = computeDuePressure(slackMinutes, pBar);
    const lane = lanesByWorkCenter.get(assignment.work_center_id);
    if (!lane) {
      continue;
    }

    const baseline = baselineByOperationId.get(assignment.operation_id);
    let shiftMinutes: number | null = null;
    if (baseline) {
      const baselineStartMs = parseIsoDate(baseline.start_time);
      const currentStartMs = parseIsoDate(assignment.start_time);
      if (baselineStartMs !== null && currentStartMs !== null) {
        shiftMinutes = (currentStartMs - baselineStartMs) / 60000.0;
      }
    }

    lane.bars.push({
      operation_id: assignment.operation_id,
      order_id: operation?.order_id ?? null,
      start_time: assignment.start_time,
      end_time: assignment.end_time,
      due_pressure: Number(duePressure.toFixed(6)),
      slack_minutes: Number(slackMinutes.toFixed(3)),
      color: pressureColor(slackMinutes, pBar),
      baseline_start_time: baseline?.start_time ?? null,
      baseline_end_time: baseline?.end_time ?? null,
      shift_minutes: shiftMinutes,
    });

    if (shiftMinutes !== null && shiftMinutes !== 0) {
      deltas.push({
        operation_id: assignment.operation_id,
        shift_minutes: Number(shiftMinutes.toFixed(3)),
        from_start_time: baseline?.start_time ?? null,
        to_start_time: assignment.start_time,
      });
    }
  }

  const precedenceLinks = operations
    .filter((operation) => operation.predecessor_op_id !== null)
    .map((operation) => ({
      operation_id: operation.id,
      predecessor_op_id: operation.predecessor_op_id,
    }));

  const lanes = Array.from(lanesByWorkCenter.values()).map((lane) => ({
    ...lane,
    bars: lane.bars.sort((left, right) => {
      const leftStart = parseIsoDate(asString(left.start_time));
      const rightStart = parseIsoDate(asString(right.start_time));
      return (leftStart ?? 0) - (rightStart ?? 0);
    }),
  }));

  return {
    lanes,
    precedence_links: precedenceLinks,
    deltas,
    summary: {
      operations: assignments.length,
      delayed_operations: assignments.filter((assignment) => {
        const operation = operationsById.get(assignment.operation_id);
        const order = operation ? ordersById.get(operation.order_id) : undefined;
        const endMs = parseIsoDate(assignment.end_time);
        const dueMs = parseIsoDate(order?.due_date ?? null);
        return endMs !== null && dueMs !== null && endMs > dueMs;
      }).length,
    },
  };
}
