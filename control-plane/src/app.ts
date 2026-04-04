import Fastify, { type FastifyInstance } from "fastify";

import { buildOpenApiDocument } from "./openapi";
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

const errorEnvelopeSchema = {
  type: "object",
  properties: {
    statusCode: { type: "integer" },
    error: { type: "string" },
    message: { type: "string" },
    errors: { type: "array" },
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

export function buildControlPlaneApp(
  options: BuildControlPlaneAppOptions = {},
): FastifyInstance {
  const schemas = loadContractSchemas();
  const validators = buildContractValidators(schemas);
  const executor = options.executor ?? createPythonContractExecutor();
  const openApiDocument = buildOpenApiDocument(schemas);
  const routeList = [
    "/healthz",
    "/openapi.json",
    "/api/v1/runtime-contract",
    "/api/v1/solve",
    "/api/v1/repair",
  ];

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
    "/api/v1/solve",
    {
      schema: {
        body: schemas.solveRequest,
        response: {
          200: schemas.solveResponse,
          400: errorEnvelopeSchema,
          502: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const payload = normalizeSolvePayload(
        withRequestId(request.body as Record<string, unknown>, request.id),
      );
      const response = await executor.executeSolveRequest(payload);

      if (!validators.solveResponse(response)) {
        return reply.code(502).send({
          statusCode: 502,
          error: "Bad Gateway",
          message: "Python solve response failed contract validation",
          errors: collectValidationFailure(
            validators.solveResponse,
            "invalid solve response",
          ).errors,
        });
      }

      return reply.code(200).send(response);
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
          502: errorEnvelopeSchema,
        },
      },
    },
    async (request, reply) => {
      const payload = withRequestId(request.body as Record<string, unknown>, request.id);
      const response = await executor.executeRepairRequest(payload);

      if (!validators.repairResponse(response)) {
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

    if (knownError instanceof SynapsPythonBridgeError) {
      return reply.code(502).send({
        statusCode: 502,
        error: "Bad Gateway",
        message: knownError.message,
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