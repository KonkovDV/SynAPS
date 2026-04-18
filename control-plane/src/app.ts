import Fastify, { type FastifyInstance } from "fastify";

import { applyAclGuardrails, AclValidationError } from "./anti-corruption";
import { buildGanttModel, type BuildGanttModelRequest } from "./gantt-view";
import { buildOpenApiDocument } from "./openapi";
import {
  closeObservedSpan,
  logObservedEvent,
  startObservedSpan,
  SynapsMetricsRegistry,
} from "./observability";
import {
  buildContractValidators,
  collectValidationFailure,
  loadContractSchemas,
  withRequestId,
} from "./runtime-contract";
import {
  createPythonContractExecutor,
  SynapsPythonBridgeError,
  type SynapsContractExecutor,
} from "./python-executor";

export interface BuildControlPlaneAppOptions {
  executor?: SynapsContractExecutor;
  logger?: boolean;
  metrics?: SynapsMetricsRegistry;
}

const errorEnvelopeSchema = {
  type: "object",
  properties: {
    statusCode: { type: "integer" },
    error: { type: "string" },
    message: { type: "string" },
    errors: { type: "array" },
    bridge_code: { type: "string" },
  },
  required: ["statusCode", "error", "message"],
} as const;

const healthResponseSchema = {
  type: "object",
  properties: {
    status: { const: "ok", type: "string" },
    surface: { const: "synaps-control-plane", type: "string" },
  },
  required: ["status", "surface"],
} as const;

const runtimeContractIndexSchema = {
  type: "object",
  properties: {
    schema_files: {
      type: "array",
      items: { type: "string" },
    },
    openapi_json: { type: "string" },
    routes: {
      type: "array",
      items: { type: "string" },
    },
  },
  required: ["schema_files", "openapi_json", "routes"],
} as const;

const metricsResponseSchema = {
  type: "string",
} as const;

const ganttRequestSchema = {
  type: "object",
  properties: {
    problem: { type: "object" },
    schedule: {
      type: "object",
      properties: {
        assignments: {
          type: "array",
          items: { type: "object" },
        },
      },
      required: ["assignments"],
    },
    baseline_schedule: {
      anyOf: [
        {
          type: "object",
          properties: {
            assignments: {
              type: "array",
              items: { type: "object" },
            },
          },
          required: ["assignments"],
        },
        { type: "null" },
      ],
    },
  },
  required: ["problem", "schedule"],
} as const;

const ganttResponseSchema = {
  type: "object",
  properties: {
    lanes: {
      type: "array",
      items: { type: "object" },
    },
    precedence_links: {
      type: "array",
      items: { type: "object" },
    },
    deltas: {
      type: "array",
      items: { type: "object" },
    },
    summary: {
      type: "object",
      properties: {
        operations: { type: "integer" },
        delayed_operations: { type: "integer" },
      },
      required: ["operations", "delayed_operations"],
    },
  },
  required: ["lanes", "precedence_links", "deltas", "summary"],
} as const;

function asObject(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function normalizeSolvePayload(payload: Record<string, unknown>): Record<string, unknown> {
  return {
    ...payload,
    solver_config:
      typeof payload.solver_config === "string" && payload.solver_config.trim().length > 0
        ? payload.solver_config
        : null,
  };
}

function normalizeRepairPayload(payload: Record<string, unknown>): Record<string, unknown> {
  return {
    ...payload,
  };
}

interface SolveAttempt {
  solver_config: string | null;
  bridge_code?: string;
  result_status?: string;
}

const DEFAULT_LIMIT_GUARD_CHAIN = ["CPSAT-30", "LBBD-10", "RHC-ALNS", "GREED"];

function parseLimitGuardChain(): string[] {
  const raw = process.env.SYNAPS_LIMIT_GUARD_CHAIN;
  if (!raw || raw.trim().length === 0) {
    return DEFAULT_LIMIT_GUARD_CHAIN;
  }

  const parsed = raw
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);

  return parsed.length > 0 ? parsed : DEFAULT_LIMIT_GUARD_CHAIN;
}

function buildSolveAttemptChain(initial: string | null, fallbackChain: string[]): Array<string | null> {
  const chain: Array<string | null> = [];
  const seen = new Set<string>();

  if (initial !== null) {
    chain.push(initial);
    seen.add(initial);
  } else {
    chain.push(null);
  }

  for (const solverConfig of fallbackChain) {
    if (seen.has(solverConfig)) {
      continue;
    }
    chain.push(solverConfig);
    seen.add(solverConfig);
  }

  return chain;
}

function shouldRetryAfterBridgeError(error: SynapsPythonBridgeError): boolean {
  return ["timeout", "oom", "output_limit"].includes(error.code);
}

function shouldRetryAfterResultStatus(status: string | null): boolean {
  if (status === null) {
    return false;
  }
  return status === "timeout" || status === "error";
}

function annotateResponseWithFallback(
  response: Record<string, unknown>,
  attempts: SolveAttempt[],
): Record<string, unknown> {
  if (attempts.length <= 1) {
    return response;
  }

  const result = asObject(response.result);
  const metadata = asObject(result.metadata);

  return {
    ...response,
    result: {
      ...result,
      metadata: {
        ...metadata,
        limit_guard: {
          applied: true,
          mode: "feasible_fallback",
          attempts,
        },
      },
    },
  };
}

function deriveHttpStatusFromBridgeError(error: SynapsPythonBridgeError): number {
  switch (error.code) {
    case "timeout":
      return 504;
    case "oom":
    case "output_limit":
      return 503;
    default:
      return 502;
  }
}

export function buildControlPlaneApp(
  options: BuildControlPlaneAppOptions = {},
): FastifyInstance {
  const schemas = loadContractSchemas();
  const validators = buildContractValidators(schemas);
  const executor = options.executor ?? createPythonContractExecutor();
  const metrics = options.metrics ?? new SynapsMetricsRegistry();
  const openApiDocument = buildOpenApiDocument(schemas);
  const routeList = [
    "/healthz",
    "/metrics",
    "/openapi.json",
    "/api/v1/runtime-contract",
    "/api/v1/solve",
    "/api/v1/repair",
    "/api/v1/ui/gantt-model",
  ];

  const fallbackChain = parseLimitGuardChain();
  const limitGuardsEnabled = process.env.SYNAPS_ENABLE_LIMIT_GUARDS !== "0";

  const app = Fastify({ logger: options.logger ?? false });

  app.get(
    "/healthz",
    {
      schema: {
        response: {
          200: healthResponseSchema,
        },
      },
    },
    async () => ({ status: "ok", surface: "synaps-control-plane" }),
  );

  app.get(
    "/metrics",
    {
      schema: {
        response: {
          200: metricsResponseSchema,
        },
      },
    },
    async (_request, reply) => {
      reply.header("content-type", "text/plain; version=0.0.4");
      return metrics.toPrometheus();
    },
  );

  app.get("/openapi.json", async () => openApiDocument);

  app.get(
    "/api/v1/runtime-contract",
    {
      schema: {
        response: {
          200: runtimeContractIndexSchema,
        },
      },
    },
    async () => ({
      schema_files: [
        "solve-request.schema.json",
        "solve-response.schema.json",
        "repair-request.schema.json",
        "repair-response.schema.json",
      ],
      openapi_json: "/openapi.json",
      routes: routeList,
    }),
  );

  app.post(
    "/api/v1/ui/gantt-model",
    {
      schema: {
        body: ganttRequestSchema,
        response: {
          200: ganttResponseSchema,
          400: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const observedSpan = startObservedSpan(
        "UI_Gantt_Model",
        { route: "/api/v1/ui/gantt-model", request_id: request.id },
      );
      reply.header("x-synaps-trace-id", observedSpan.traceId);

      try {
        const model = buildGanttModel(request.body as BuildGanttModelRequest);
        closeObservedSpan(observedSpan, "ok");
        return reply.code(200).send(model);
      } catch (error) {
        closeObservedSpan(observedSpan, "error", { error: String(error) });
        throw error;
      }
    },
  );

  app.post(
    "/api/v1/solve",
    {
      schema: {
        body: schemas.solveRequest,
        response: {
          200: schemas.solveResponse,
          400: errorEnvelopeSchema,
          422: errorEnvelopeSchema,
          502: errorEnvelopeSchema,
          503: errorEnvelopeSchema,
          504: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const rootSpan = startObservedSpan("Solve_Request", {
        route: "/api/v1/solve",
        request_id: request.id,
      });
      reply.header("x-synaps-trace-id", rootSpan.traceId);
      logObservedEvent(app.log, "info", "solve_request_received", rootSpan);

      const rawPayload = normalizeSolvePayload(
        withRequestId(request.body as Record<string, unknown>, request.id),
      );

      const preValidationSpan = startObservedSpan(
        "Feasibility_Check_Pre",
        { request_id: request.id },
        rootSpan,
      );
      const guardedPayload: Record<string, unknown> = {
        ...rawPayload,
        problem: applyAclGuardrails(rawPayload.problem),
      };
      closeObservedSpan(preValidationSpan, "ok");

      const solveAttemptChain = buildSolveAttemptChain(
        asString(guardedPayload.solver_config),
        fallbackChain,
      );

      const attempts: SolveAttempt[] = [];
      let lastBridgeError: SynapsPythonBridgeError | null = null;
      let lastContractFailure: Record<string, unknown> | null = null;

      for (let index = 0; index < solveAttemptChain.length; index += 1) {
        const solverConfig = solveAttemptChain[index];
        const attemptSpan = startObservedSpan(
          `Solver_Execution_${solverConfig ?? "AUTO"}`,
          {
            request_id: request.id,
            solver_config: solverConfig ?? "AUTO",
            attempt: index + 1,
          },
          rootSpan,
        );

        const attemptPayload = normalizeSolvePayload({
          ...guardedPayload,
          solver_config: solverConfig,
        });

        try {
          const response = await executor.executeSolveRequest(attemptPayload);

          if (!validators.solveResponse(response)) {
            const failure = {
              statusCode: 502,
              error: "Bad Gateway",
              message: "Python solve response failed contract validation",
              errors: collectValidationFailure(
                validators.solveResponse,
                "invalid solve response",
              ).errors,
            };
            lastContractFailure = failure;
            closeObservedSpan(attemptSpan, "error", { contract_validation: false });
            break;
          }

          const normalizedResponse = annotateResponseWithFallback(
            response as Record<string, unknown>,
            attempts,
          );
          const result = asObject(normalizedResponse.result);
          const status = asString(result.status);

          attempts.push({
            solver_config: solverConfig,
            result_status: status ?? undefined,
          });
          metrics.recordScheduleResult(result);

          logObservedEvent(app.log, "info", "solve_attempt_completed", attemptSpan, {
            solver_config: solverConfig,
            result_status: status,
            limit_guards_enabled: limitGuardsEnabled,
          });

          if (
            limitGuardsEnabled &&
            shouldRetryAfterResultStatus(status) &&
            index < solveAttemptChain.length - 1
          ) {
            closeObservedSpan(attemptSpan, "error", {
              retry_next_solver: true,
              result_status: status ?? "unknown",
            });
            continue;
          }

          closeObservedSpan(attemptSpan, "ok", {
            final_result_status: status ?? "unknown",
          });
          closeObservedSpan(rootSpan, "ok", {
            attempts: attempts.length,
            final_solver: solverConfig ?? "AUTO",
          });

          return reply.code(200).send(
            annotateResponseWithFallback(normalizedResponse, attempts),
          );
        } catch (error) {
          if (error instanceof SynapsPythonBridgeError) {
            lastBridgeError = error;
            attempts.push({
              solver_config: solverConfig,
              bridge_code: error.code,
            });

            logObservedEvent(app.log, "warn", "solve_attempt_bridge_error", attemptSpan, {
              solver_config: solverConfig,
              bridge_code: error.code,
              limit_guards_enabled: limitGuardsEnabled,
            });

            const canRetry =
              limitGuardsEnabled &&
              shouldRetryAfterBridgeError(error) &&
              index < solveAttemptChain.length - 1;

            closeObservedSpan(attemptSpan, "error", {
              bridge_code: error.code,
              retry_next_solver: canRetry,
            });

            if (canRetry) {
              continue;
            }
          }

          closeObservedSpan(rootSpan, "error", {
            attempts: attempts.length,
          });
          throw error;
        }
      }

      closeObservedSpan(rootSpan, "error", {
        attempts: attempts.length,
      });

      if (lastContractFailure !== null) {
        return reply.code(502).send(lastContractFailure);
      }

      if (lastBridgeError !== null) {
        const statusCode = deriveHttpStatusFromBridgeError(lastBridgeError);
        if (statusCode === 504) {
          return reply.code(504).send({
            statusCode: 504,
            error: "Gateway Timeout",
            message: lastBridgeError.message,
            bridge_code: lastBridgeError.code,
          });
        }

        if (statusCode === 503) {
          return reply.code(503).send({
            statusCode: 503,
            error: "Bad Gateway",
            message: lastBridgeError.message,
            bridge_code: lastBridgeError.code,
          });
        }

        return reply.code(502).send({
          statusCode: 502,
          error: "Bad Gateway",
          message: lastBridgeError.message,
          bridge_code: lastBridgeError.code,
        });
      }

      return reply.code(502).send({
        statusCode: 502,
        error: "Bad Gateway",
        message: "Solve request exhausted fallback chain without a valid response",
      });
    },
  );

  app.post(
    "/api/v1/repair",
    {
      schema: {
        body: schemas.repairRequest,
        response: {
          200: schemas.repairResponse,
          400: errorEnvelopeSchema,
          422: errorEnvelopeSchema,
          502: errorEnvelopeSchema,
          503: errorEnvelopeSchema,
          504: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const rootSpan = startObservedSpan("Repair_Request", {
        route: "/api/v1/repair",
        request_id: request.id,
      });
      reply.header("x-synaps-trace-id", rootSpan.traceId);

      const rawPayload = normalizeRepairPayload(
        withRequestId(request.body as Record<string, unknown>, request.id),
      );

      const preValidationSpan = startObservedSpan(
        "Feasibility_Check_Pre",
        { request_id: request.id },
        rootSpan,
      );
      const guardedPayload = {
        ...rawPayload,
        problem: applyAclGuardrails(rawPayload.problem),
      };
      closeObservedSpan(preValidationSpan, "ok");

      const solverSpan = startObservedSpan(
        "Solver_Execution_INCREMENTAL_REPAIR",
        { request_id: request.id },
        rootSpan,
      );

      const response = await executor.executeRepairRequest(guardedPayload);

      if (!validators.repairResponse(response)) {
        closeObservedSpan(solverSpan, "error", { contract_validation: false });
        closeObservedSpan(rootSpan, "error");
        return reply.code(502).send({
          statusCode: 502,
          error: "Bad Gateway",
          message: "Python repair response failed contract validation",
          errors: collectValidationFailure(
            validators.repairResponse,
            "invalid repair response",
          ).errors,
        });
      }

      const result = asObject(asObject(response).result);
      metrics.recordScheduleResult(result);

      closeObservedSpan(solverSpan, "ok", {
        result_status: asString(result.status) ?? "unknown",
      });
      closeObservedSpan(rootSpan, "ok");

      return reply.code(200).send(response);
    },
  );

  app.setErrorHandler((error, _request, reply) => {
    const knownError = error instanceof Error ? error : new Error(String(error));
    const maybeValidationError = knownError as Error & { validation?: unknown };

    if (maybeValidationError.validation) {
      return reply.code(400).send({
        statusCode: 400,
        error: "Bad Request",
        message: knownError.message,
        errors: maybeValidationError.validation,
      });
    }

    if (knownError instanceof AclValidationError) {
      return reply.code(422).send({
        statusCode: 422,
        error: "Unprocessable Entity",
        message: knownError.message,
        errors: knownError.issues,
      });
    }

    if (knownError instanceof SynapsPythonBridgeError) {
      const statusCode = deriveHttpStatusFromBridgeError(knownError);
      if (statusCode === 504) {
        return reply.code(504).send({
          statusCode: 504,
          error: "Gateway Timeout",
          message: knownError.message,
          bridge_code: knownError.code,
        });
      }

      if (statusCode === 503) {
        return reply.code(503).send({
          statusCode: 503,
          error: "Bad Gateway",
          message: knownError.message,
          bridge_code: knownError.code,
        });
      }

      return reply.code(502).send({
        statusCode: 502,
        error: "Bad Gateway",
        message: knownError.message,
        bridge_code: knownError.code,
      });
    }

    reply.code(500).send({
      statusCode: 500,
      error: "Internal Server Error",
      message: knownError.message,
    });
  });

  return app;
}
