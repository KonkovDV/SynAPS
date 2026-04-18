import { randomBytes } from "node:crypto";

import {
  SpanKind,
  SpanStatusCode,
  context,
  trace,
  type Span,
  type SpanContext,
} from "@opentelemetry/api";
import type { FastifyBaseLogger } from "fastify";

const ZERO_TRACE_ID = "00000000000000000000000000000000";
const ZERO_SPAN_ID = "0000000000000000";
const DURATION_BUCKETS = [0.1, 1, 10, 60, 300, 3600] as const;

export interface ObservedSpan {
  name: string;
  traceId: string;
  spanId: string;
  startedAt: number;
  span: Span;
}

export type FeasibilityViolationKind =
  | "precedence"
  | "overlap"
  | "setup_capacity"
  | "aux_capacity"
  | "unknown";

function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}

function normalizeSpanContext(spanContext: SpanContext): { traceId: string; spanId: string } {
  return {
    traceId: spanContext.traceId === ZERO_TRACE_ID ? randomHex(16) : spanContext.traceId,
    spanId: spanContext.spanId === ZERO_SPAN_ID ? randomHex(8) : spanContext.spanId,
  };
}

export function startObservedSpan(
  name: string,
  attributes: Record<string, string | number | boolean>,
  parent?: ObservedSpan,
): ObservedSpan {
  const tracer = trace.getTracer("synaps-control-plane");
  const parentContext = parent
    ? trace.setSpan(context.active(), parent.span)
    : context.active();
  const span = tracer.startSpan(name, { kind: SpanKind.INTERNAL, attributes }, parentContext);
  const ids = normalizeSpanContext(span.spanContext());

  return {
    name,
    traceId: ids.traceId,
    spanId: ids.spanId,
    startedAt: Date.now(),
    span,
  };
}

export function closeObservedSpan(
  observedSpan: ObservedSpan,
  status: "ok" | "error",
  attributes: Record<string, string | number | boolean> = {},
): number {
  const durationMs = Date.now() - observedSpan.startedAt;
  observedSpan.span.setAttributes({ ...attributes, "span.duration_ms": durationMs });
  observedSpan.span.setStatus({ code: status === "ok" ? SpanStatusCode.OK : SpanStatusCode.ERROR });
  observedSpan.span.end();
  return durationMs;
}

export function logObservedEvent(
  logger: FastifyBaseLogger,
  level: "info" | "warn" | "error",
  event: string,
  observedSpan: ObservedSpan,
  fields: Record<string, unknown> = {},
): void {
  logger[level](
    {
      event,
      trace_id: observedSpan.traceId,
      span_id: observedSpan.spanId,
      span_name: observedSpan.name,
      ...fields,
    },
    event,
  );
}

interface HistogramState {
  counts: number[];
  sum: number;
  total: number;
}

function createHistogramState(): HistogramState {
  return {
    counts: new Array(DURATION_BUCKETS.length).fill(0),
    sum: 0,
    total: 0,
  };
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number") {
    return null;
  }
  return Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function normalizeMetricLabel(value: string | null | undefined, fallback: string): string {
  if (value === null || value === undefined) {
    return fallback;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : fallback;
}

function asNonNegativeInteger(value: unknown): number | null {
  const parsed = asFiniteNumber(value);
  if (parsed === null || parsed < 0) {
    return null;
  }
  return Math.floor(parsed);
}

function asObject(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

function prometheusEscape(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("\"", "\\\"");
}

export class SynapsMetricsRegistry {
  private readonly solveDuration = createHistogramState();
  private readonly feasibilityCounters = new Map<FeasibilityViolationKind, number>();
  private readonly solverRunCounters = new Map<string, Map<string, number>>();
  private readonly bridgeErrorCounters = new Map<string, Map<string, number>>();
  private readonly limitGuardTransitionCounters = new Map<
    string,
    Map<string, Map<string, number>>
  >();
  private activeWindowsGauge = 0;
  private gapRatioGauge = 0;

  observeSolveDuration(seconds: number): void {
    if (!Number.isFinite(seconds) || seconds < 0) {
      return;
    }

    this.solveDuration.total += 1;
    this.solveDuration.sum += seconds;

    DURATION_BUCKETS.forEach((bucket, index) => {
      if (seconds <= bucket) {
        this.solveDuration.counts[index] += 1;
      }
    });
  }

  incrementFeasibilityViolation(kind: FeasibilityViolationKind, count = 1): void {
    if (count <= 0) {
      return;
    }
    this.feasibilityCounters.set(kind, (this.feasibilityCounters.get(kind) ?? 0) + count);
  }

  incrementSolverRun(solverConfig: string, status: string, count = 1): void {
    if (count <= 0) {
      return;
    }

    const solverConfigKey = solverConfig.trim().length > 0 ? solverConfig.trim() : "UNKNOWN";
    const statusKey = status.trim().length > 0 ? status.trim().toLowerCase() : "unknown";

    const statusCounters = this.solverRunCounters.get(solverConfigKey) ?? new Map<string, number>();
    statusCounters.set(statusKey, (statusCounters.get(statusKey) ?? 0) + count);
    this.solverRunCounters.set(solverConfigKey, statusCounters);
  }

  incrementBridgeError(solverConfig: string, code: string, count = 1): void {
    if (count <= 0) {
      return;
    }

    const solverConfigKey = normalizeMetricLabel(solverConfig, "UNKNOWN");
    const codeKey = normalizeMetricLabel(code, "unknown").toLowerCase();

    const codeCounters = this.bridgeErrorCounters.get(solverConfigKey) ?? new Map<string, number>();
    codeCounters.set(codeKey, (codeCounters.get(codeKey) ?? 0) + count);
    this.bridgeErrorCounters.set(solverConfigKey, codeCounters);
  }

  incrementLimitGuardTransition(
    fromSolver: string,
    toSolver: string,
    reason: string,
    count = 1,
  ): void {
    if (count <= 0) {
      return;
    }

    const fromSolverKey = normalizeMetricLabel(fromSolver, "UNKNOWN");
    const toSolverKey = normalizeMetricLabel(toSolver, "UNKNOWN");
    const reasonKey = normalizeMetricLabel(reason, "unknown").toLowerCase();

    const toSolverCounters =
      this.limitGuardTransitionCounters.get(fromSolverKey) ??
      new Map<string, Map<string, number>>();
    const reasonCounters = toSolverCounters.get(toSolverKey) ?? new Map<string, number>();

    reasonCounters.set(reasonKey, (reasonCounters.get(reasonKey) ?? 0) + count);
    toSolverCounters.set(toSolverKey, reasonCounters);
    this.limitGuardTransitionCounters.set(fromSolverKey, toSolverCounters);
  }

  setActiveWindows(value: number): void {
    if (!Number.isFinite(value) || value < 0) {
      return;
    }
    this.activeWindowsGauge = value;
  }

  setGapRatio(value: number): void {
    if (!Number.isFinite(value) || value < 0) {
      return;
    }
    this.gapRatioGauge = value;
  }

  recordScheduleResult(result: unknown): void {
    const resultObject = asObject(result);
    const durationMs = asFiniteNumber(resultObject.duration_ms);
    if (durationMs !== null) {
      this.observeSolveDuration(durationMs / 1000.0);
    }

    const metadata = asObject(resultObject.metadata);
    const portfolioMetadata = asObject(metadata.portfolio);

    const solverConfig =
      asString(portfolioMetadata.solver_config) ??
      asString(metadata.solver_config) ??
      asString(resultObject.solver_name) ??
      "UNKNOWN";
    const status = asString(resultObject.status) ?? "unknown";
    this.incrementSolverRun(solverConfig, status);

    const windowsSolved = asFiniteNumber(
      metadata.windows_solved ?? portfolioMetadata.windows_solved,
    );
    if (windowsSolved !== null) {
      this.setActiveWindows(windowsSolved);
    }

    const gapRatio = asFiniteNumber(metadata.gap ?? portfolioMetadata.gap);
    if (gapRatio !== null) {
      this.setGapRatio(gapRatio);
    }

    const finalViolations = asNonNegativeInteger(
      metadata.final_violations ??
        metadata.violation_count ??
        portfolioMetadata.final_violations ??
        portfolioMetadata.violation_count,
    );
    const rawKinds = asObject(
      metadata.feasibility_violation_kinds ??
        metadata.violation_kind_counts ??
        portfolioMetadata.feasibility_violation_kinds ??
        portfolioMetadata.violation_kind_counts,
    );

    if (Object.keys(rawKinds).length > 0) {
      for (const [rawKind, rawCount] of Object.entries(rawKinds)) {
        const count = asNonNegativeInteger(rawCount);
        if (count === null || count <= 0) {
          continue;
        }

        const normalizedKind = rawKind.toLowerCase();
        let kind: FeasibilityViolationKind = "unknown";
        if (normalizedKind.includes("preced")) {
          kind = "precedence";
        } else if (normalizedKind.includes("overlap")) {
          kind = "overlap";
        } else if (normalizedKind.includes("setup")) {
          kind = "setup_capacity";
        } else if (
          normalizedKind.includes("aux") ||
          normalizedKind.includes("resource")
        ) {
          kind = "aux_capacity";
        }
        this.incrementFeasibilityViolation(kind, count);
      }
      return;
    }

    if (finalViolations !== null && finalViolations > 0) {
      this.incrementFeasibilityViolation("unknown", finalViolations);
    }
  }

  toPrometheus(): string {
    const lines: string[] = [];

    lines.push("# HELP synaps_solve_duration_seconds Solve duration distribution.");
    lines.push("# TYPE synaps_solve_duration_seconds histogram");

    DURATION_BUCKETS.forEach((bucket, index) => {
      lines.push(
        `synaps_solve_duration_seconds_bucket{le=\"${bucket}\"} ${this.solveDuration.counts[index]}`,
      );
    });
    lines.push(
      `synaps_solve_duration_seconds_bucket{le=\"+Inf\"} ${this.solveDuration.total}`,
    );
    lines.push(`synaps_solve_duration_seconds_sum ${this.solveDuration.sum}`);
    lines.push(`synaps_solve_duration_seconds_count ${this.solveDuration.total}`);

    lines.push(
      "# HELP synaps_solver_runs_total Total solver outcomes by solver_config and status.",
    );
    lines.push("# TYPE synaps_solver_runs_total counter");
    const solverEntries = Array.from(this.solverRunCounters.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    for (const [solverConfig, statusCounters] of solverEntries) {
      const statusEntries = Array.from(statusCounters.entries()).sort(([left], [right]) =>
        left.localeCompare(right),
      );
      for (const [status, value] of statusEntries) {
        lines.push(
          `synaps_solver_runs_total{solver_config=\"${prometheusEscape(solverConfig)}\",status=\"${prometheusEscape(status)}\"} ${value}`,
        );
      }
    }

    lines.push(
      "# HELP synaps_limit_guard_transitions_total Total limit-guard fallback transitions by from/to solver and reason.",
    );
    lines.push("# TYPE synaps_limit_guard_transitions_total counter");
    const transitionFromEntries = Array.from(this.limitGuardTransitionCounters.entries()).sort(
      ([left], [right]) => left.localeCompare(right),
    );
    for (const [fromSolver, toSolverCounters] of transitionFromEntries) {
      const transitionToEntries = Array.from(toSolverCounters.entries()).sort(([left], [right]) =>
        left.localeCompare(right),
      );
      for (const [toSolver, reasonCounters] of transitionToEntries) {
        const reasonEntries = Array.from(reasonCounters.entries()).sort(([left], [right]) =>
          left.localeCompare(right),
        );
        for (const [reason, value] of reasonEntries) {
          lines.push(
            `synaps_limit_guard_transitions_total{from_solver=\"${prometheusEscape(fromSolver)}\",to_solver=\"${prometheusEscape(toSolver)}\",reason=\"${prometheusEscape(reason)}\"} ${value}`,
          );
        }
      }
    }

    lines.push(
      "# HELP synaps_bridge_errors_total Total bridge errors by solver_config and bridge error code.",
    );
    lines.push("# TYPE synaps_bridge_errors_total counter");
    const bridgeEntries = Array.from(this.bridgeErrorCounters.entries()).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    for (const [solverConfig, codeCounters] of bridgeEntries) {
      const codeEntries = Array.from(codeCounters.entries()).sort(([left], [right]) =>
        left.localeCompare(right),
      );
      for (const [code, value] of codeEntries) {
        lines.push(
          `synaps_bridge_errors_total{solver_config=\"${prometheusEscape(solverConfig)}\",code=\"${prometheusEscape(code)}\"} ${value}`,
        );
      }
    }

    lines.push(
      "# HELP synaps_feasibility_violations_total Total feasibility violations by kind.",
    );
    lines.push("# TYPE synaps_feasibility_violations_total counter");
    for (const [kind, value] of this.feasibilityCounters.entries()) {
      lines.push(
        `synaps_feasibility_violations_total{kind=\"${prometheusEscape(kind)}\"} ${value}`,
      );
    }

    lines.push("# HELP synaps_active_windows_gauge Active windows solved in latest request.");
    lines.push("# TYPE synaps_active_windows_gauge gauge");
    lines.push(`synaps_active_windows_gauge ${this.activeWindowsGauge}`);

    lines.push("# HELP synaps_gap_ratio Latest observed optimality gap ratio.");
    lines.push("# TYPE synaps_gap_ratio gauge");
    lines.push(`synaps_gap_ratio ${this.gapRatioGauge}`);

    return `${lines.join("\n")}\n`;
  }
}
