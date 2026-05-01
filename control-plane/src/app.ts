import { timingSafeEqual } from "node:crypto";
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
import {
  InMemorySolveJobStore,
  type SolveJobError,
  type SynapsSolveJobStore,
} from "./solve-jobs";

export interface BuildControlPlaneAppOptions {
  executor?: SynapsContractExecutor;
  logger?: boolean;
  metrics?: SynapsMetricsRegistry;
  solveJobs?: SynapsSolveJobStore;
  apiKey?: string | null;
  bodyLimitBytes?: number;
  rateLimit?: {
    maxRequests: number;
    windowMs: number;
  } | null;
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

const solveJobAcceptedSchema = {
  type: "object",
  properties: {
    job_id: { type: "string" },
    request_id: { type: "string" },
    status: { enum: ["pending", "running", "succeeded", "failed"] },
    status_url: { type: "string" },
    created_at: { type: "string" },
    started_at: { anyOf: [{ type: "string" }, { type: "null" }] },
    completed_at: { anyOf: [{ type: "string" }, { type: "null" }] },
    result: {
      anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }],
    },
    error: { anyOf: [errorEnvelopeSchema, { type: "null" }] },
  },
  required: [
    "job_id",
    "request_id",
    "status",
    "status_url",
    "created_at",
    "started_at",
    "completed_at",
    "result",
    "error",
  ],
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

function maybeApplyAclGuardrails(problem: unknown): unknown {
  return problem == null ? problem : applyAclGuardrails(problem);
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

function parsePositiveInteger(value: string | undefined): number | null {
  if (value === undefined || value.trim().length === 0) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return Math.floor(parsed);
}

function resolveControlPlaneApiKey(optionValue: string | null | undefined): string | null {
  if (optionValue !== undefined) {
    return optionValue && optionValue.trim().length > 0 ? optionValue : null;
  }
  const value = process.env.SYNAPS_CONTROL_PLANE_API_KEY;
  return value && value.trim().length > 0 ? value : null;
}

function resolveBodyLimitBytes(optionValue: number | undefined): number {
  if (optionValue !== undefined && Number.isFinite(optionValue) && optionValue > 0) {
    return Math.floor(optionValue);
  }
  return parsePositiveInteger(process.env.SYNAPS_CONTROL_PLANE_MAX_BODY_BYTES) ?? 10_000_000;
}

function resolveRateLimit(
  optionValue: BuildControlPlaneAppOptions["rateLimit"] | undefined,
): { maxRequests: number; windowMs: number } | null {
  if (optionValue !== undefined) {
    return optionValue;
  }
  const maxRequests = parsePositiveInteger(process.env.SYNAPS_CONTROL_PLANE_RATE_LIMIT_MAX);
  if (maxRequests === null) {
    return null;
  }
  return {
    maxRequests,
    windowMs:
      parsePositiveInteger(process.env.SYNAPS_CONTROL_PLANE_RATE_LIMIT_WINDOW_MS) ?? 60_000,
  };
}

function matchesControlPlaneApiKey(
  presentedApiKey: string | null,
  expectedApiKey: string,
): boolean {
  if (presentedApiKey === null) {
    return false;
  }
  const presentedBuffer = Buffer.from(presentedApiKey, "utf-8");
  const expectedBuffer = Buffer.from(expectedApiKey, "utf-8");
  return (
    presentedBuffer.length === expectedBuffer.length &&
    timingSafeEqual(presentedBuffer, expectedBuffer)
  );
}

function extractPresentedApiKey(request: {
  headers: Record<string, string | string[] | undefined>;
}): string | null {
  const apiKeyHeader = request.headers["x-api-key"];
  if (typeof apiKeyHeader === "string" && apiKeyHeader.trim().length > 0) {
    return apiKeyHeader.trim();
  }
  const authorizationHeader = request.headers.authorization;
  if (typeof authorizationHeader !== "string") {
    return null;
  }
  const bearerMatch = authorizationHeader.match(/^\s*Bearer\s+(.+?)\s*$/i);
  return bearerMatch?.[1] ?? null;
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

function serializeSolveJobError(error: unknown): SolveJobError {
  if (error instanceof SynapsPythonBridgeError) {
    const statusCode = deriveHttpStatusFromBridgeError(error);
    return {
      statusCode,
      error: statusCode === 504 ? "Gateway Timeout" : "Bad Gateway",
      message: error.message,
      bridge_code: error.code,
    };
  }

  const maybeEnvelope = asObject(error);
  const statusCode =
    typeof maybeEnvelope.statusCode === "number" ? maybeEnvelope.statusCode : 500;
  const errorText = asString(maybeEnvelope.error) ?? "Internal Server Error";
  const message = asString(maybeEnvelope.message) ?? String(error);
  const serialized: SolveJobError = {
    statusCode,
    error: errorText,
    message,
  };
  if ("errors" in maybeEnvelope) {
    serialized.errors = maybeEnvelope.errors;
  }
  if (typeof maybeEnvelope.bridge_code === "string") {
    serialized.bridge_code = maybeEnvelope.bridge_code;
  }
  return serialized;
}

export function buildControlPlaneApp(
  options: BuildControlPlaneAppOptions = {},
): FastifyInstance {
  const schemas = loadContractSchemas();
  const validators = buildContractValidators(schemas);
  const executor = options.executor ?? createPythonContractExecutor();
  const metrics = options.metrics ?? new SynapsMetricsRegistry();
  const solveJobs = options.solveJobs ?? new InMemorySolveJobStore();
  const openApiDocument = buildOpenApiDocument(schemas);
  const apiKey = resolveControlPlaneApiKey(options.apiKey);
  const rateLimit = resolveRateLimit(options.rateLimit);
  const rateLimitBuckets = new Map<string, { resetAt: number; count: number }>();
  const routeList = [
    "/healthz",
    "/metrics",
    "/openapi.json",
    "/api/v1/runtime-contract",
    "/api/v1/solve",
    "/api/v1/solve/jobs",
    "/api/v1/solve/jobs/:jobId",
    "/api/v1/repair",
    "/api/v1/ui/gantt-model",
  ];

  const solveJobStatusSchema = {
    ...solveJobAcceptedSchema,
    properties: {
      ...solveJobAcceptedSchema.properties,
      result: {
        anyOf: [{ type: "object", additionalProperties: true }, { type: "null" }],
      },
    },
  };

  const fallbackChain = parseLimitGuardChain();
  const limitGuardsEnabled = process.env.SYNAPS_ENABLE_LIMIT_GUARDS !== "0";

  const app = Fastify({
    logger: options.logger ?? false,
    bodyLimit: resolveBodyLimitBytes(options.bodyLimitBytes),
  });

  app.addHook("onRequest", async (request, reply) => {
    if (apiKey !== null) {
      const presentedApiKey = extractPresentedApiKey(request);
      if (!matchesControlPlaneApiKey(presentedApiKey, apiKey)) {
        reply.code(401).send({
          statusCode: 401,
          error: "Unauthorized",
          message: "Missing or invalid SynAPS control-plane API key",
        });
        return;
      }
    }

    if (rateLimit !== null) {
      const key = request.ip;
      const now = Date.now();
      const bucket = rateLimitBuckets.get(key);
      if (bucket === undefined || bucket.resetAt <= now) {
        rateLimitBuckets.set(key, { resetAt: now + rateLimit.windowMs, count: 1 });
        return;
      }
      bucket.count += 1;
      if (bucket.count > rateLimit.maxRequests) {
        return reply.code(429).send({
          statusCode: 429,
          error: "Too Many Requests",
          message: "SynAPS control-plane rate limit exceeded",
        });
      }
    }
  });

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
        problem: maybeApplyAclGuardrails(rawPayload.problem),
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
            const fromSolver = solverConfig ?? "AUTO";
            const toSolver = solveAttemptChain[index + 1] ?? "AUTO";
            metrics.incrementLimitGuardTransition(
              fromSolver,
              toSolver,
              `status_${(status ?? "unknown").toLowerCase()}`,
            );

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
            const fromSolver = solverConfig ?? "AUTO";
            metrics.incrementBridgeError(fromSolver, error.code);

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

            if (canRetry) {
              const toSolver = solveAttemptChain[index + 1] ?? "AUTO";
              metrics.incrementLimitGuardTransition(
                fromSolver,
                toSolver,
                `bridge_${error.code}`,
              );
            }

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
    "/api/v1/solve/jobs",
    {
      schema: {
        body: schemas.solveRequest,
        response: {
          202: solveJobAcceptedSchema,
          400: errorEnvelopeSchema,
          422: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const rawPayload = normalizeSolvePayload(
        withRequestId(request.body as Record<string, unknown>, request.id),
      );
      const guardedPayload: Record<string, unknown> = {
        ...rawPayload,
        problem: maybeApplyAclGuardrails(rawPayload.problem),
      };
      const requestId = asString(guardedPayload.request_id) ?? request.id;

      const job = solveJobs.enqueueSolveJob({
        requestId,
        statusUrlBase: "/api/v1/solve/jobs",
        run: async () => {
          const response = await executor.executeSolveRequest(guardedPayload);
          if (!validators.solveResponse(response)) {
            throw {
              statusCode: 502,
              error: "Bad Gateway",
              message: "Python solve response failed contract validation",
              errors: collectValidationFailure(
                validators.solveResponse,
                "invalid solve response",
              ).errors,
            };
          }

          const result = asObject(asObject(response).result);
          metrics.recordScheduleResult(result);
          return response as Record<string, unknown>;
        },
        serializeError: serializeSolveJobError,
      });

      return reply.code(202).send(job);
    },
  );

  app.get(
    "/api/v1/solve/jobs/:jobId",
    {
      schema: {
        response: {
          200: solveJobStatusSchema,
          404: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const job = solveJobs.getSolveJob(asObject(request.params).jobId as string);
      if (job === null) {
        return reply.code(404).send({
          statusCode: 404,
          error: "Not Found",
          message: "Solve job not found",
        });
      }
      return reply.code(200).send(job);
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
