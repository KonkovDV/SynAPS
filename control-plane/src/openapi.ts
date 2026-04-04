import type { SynapsContractSchemas } from "./runtime-contract";

type JsonObject = Record<string, unknown>;

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

function withSchemaId(schema: object, id: string): JsonObject {
  return {
    ...(schema as JsonObject),
    $id: id,
  };
}

export function buildOpenApiDocument(schemas: SynapsContractSchemas): JsonObject {
  return {
    openapi: "3.1.0",
    jsonSchemaDialect: "https://json-schema.org/draft/2020-12/schema",
    info: {
      title: "SynAPS Control Plane API",
      version: "0.1.0",
      description:
        "Minimal TypeScript BFF for validating SynAPS runtime contracts and invoking the Python kernel.",
    },
    paths: {
      "/healthz": {
        get: {
          summary: "Health check",
          operationId: "getHealthz",
          responses: {
            200: {
              description: "Healthy control-plane surface",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/HealthResponse" },
                },
              },
            },
          },
        },
      },
      "/openapi.json": {
        get: {
          summary: "OpenAPI document",
          operationId: "getOpenApiDocument",
          responses: {
            200: {
              description: "OpenAPI 3.1 document",
              content: {
                "application/json": {
                  schema: {
                    type: "object",
                  },
                },
              },
            },
          },
        },
      },
      "/api/v1/runtime-contract": {
        get: {
          summary: "Runtime contract index",
          operationId: "getRuntimeContractIndex",
          responses: {
            200: {
              description: "Checked-in contract bundle index",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/RuntimeContractIndex" },
                },
              },
            },
          },
        },
      },
      "/api/v1/solve": {
        post: {
          summary: "Solve a schedule",
          operationId: "postSolve",
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/SolveRequest" },
              },
            },
          },
          responses: {
            200: {
              description: "Validated solve response",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/SolveResponse" },
                },
              },
            },
            400: {
              description: "Bad request",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/ErrorEnvelope" },
                },
              },
            },
            502: {
              description: "Upstream bridge or contract failure",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/ErrorEnvelope" },
                },
              },
            },
          },
        },
      },
      "/api/v1/repair": {
        post: {
          summary: "Repair a schedule around disrupted operations",
          operationId: "postRepair",
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: { $ref: "#/components/schemas/RepairRequest" },
              },
            },
          },
          responses: {
            200: {
              description: "Validated repair response",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/RepairResponse" },
                },
              },
            },
            400: {
              description: "Bad request",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/ErrorEnvelope" },
                },
              },
            },
            502: {
              description: "Upstream bridge or contract failure",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/ErrorEnvelope" },
                },
              },
            },
          },
        },
      },
    },
    components: {
      schemas: {
        HealthResponse: healthResponseSchema,
        RuntimeContractIndex: runtimeContractIndexSchema,
        ErrorEnvelope: errorEnvelopeSchema,
        SolveRequest: withSchemaId(
          schemas.solveRequest,
          "https://synaps.local/schemas/SolveRequest",
        ),
        SolveResponse: withSchemaId(
          schemas.solveResponse,
          "https://synaps.local/schemas/SolveResponse",
        ),
        RepairRequest: withSchemaId(
          schemas.repairRequest,
          "https://synaps.local/schemas/RepairRequest",
        ),
        RepairResponse: withSchemaId(
          schemas.repairResponse,
          "https://synaps.local/schemas/RepairResponse",
        ),
      },
    },
  };
}