import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { buildControlPlaneApp } from "../src/app";
import type { SynapsContractExecutor } from "../src/python-executor";
import { resolveSynapsRepoRoot } from "../src/paths";

function loadTinyProblem(): unknown {
  const filePath = path.join(
    resolveSynapsRepoRoot(process.cwd()),
    "benchmark",
    "instances",
    "tiny_3x3.json",
  );
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

function createSolveRequest(): Record<string, unknown> {
  return {
    contract_version: "2026-04-03",
    problem: loadTinyProblem(),
    context: {
      regime: "nominal",
      exact_required: false,
      preferred_max_latency_s: null,
    },
    verify_feasibility: true,
    solve_options: {},
  };
}

type OpenApiDocument = {
  openapi: string;
  components: {
    schemas: Record<string, unknown>;
  };
  paths: Record<
    string,
    {
      post?: {
        requestBody: {
          content: {
            "application/json": {
              schema: {
                $ref: string;
              };
            };
          };
        };
      };
    }
  >;
};

test("health endpoint returns ok", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({ method: "GET", url: "/healthz" });
  assert.equal(response.statusCode, 200);
  assert.deepEqual(response.json(), { status: "ok", surface: "synaps-control-plane" });

  await app.close();
});

test("runtime contract index exposes discoverability metadata", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({ method: "GET", url: "/api/v1/runtime-contract" });
  assert.equal(response.statusCode, 200);

  const payload = response.json() as {
    schema_files: string[];
    openapi_json: string;
    routes: string[];
  };
  assert.equal(payload.openapi_json, "/openapi.json");
  assert.ok(payload.schema_files.includes("repair-request.schema.json"));
  assert.ok(payload.routes.includes("/api/v1/repair"));

  await app.close();
});

test("openapi route exposes solve and repair schemas", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({ method: "GET", url: "/openapi.json" });
  assert.equal(response.statusCode, 200);

  const payload = response.json() as OpenApiDocument;
  assert.equal(payload.openapi, "3.1.0");
  assert.ok(payload.components.schemas.SolveRequest);
  assert.ok(payload.components.schemas.RepairRequest);
  assert.equal(
    payload.paths["/api/v1/solve"].post?.requestBody.content["application/json"].schema.$ref,
    "#/components/schemas/SolveRequest",
  );
  assert.equal(
    payload.paths["/api/v1/repair"].post?.requestBody.content["application/json"].schema.$ref,
    "#/components/schemas/RepairRequest",
  );

  await app.close();
});

test("solve route validates request body", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: {},
  });

  assert.equal(response.statusCode, 400);
  const payload = response.json() as { error: string };
  assert.equal(payload.error, "Bad Request");

  await app.close();
});

test("solve route injects request id and returns validated response", async () => {
  let seenRequestId: string | undefined;
  const executor: SynapsContractExecutor = {
    async executeSolveRequest(payload: object): Promise<unknown> {
      const request = payload as { request_id?: string };
      seenRequestId = request.request_id;
      return {
        contract_version: "2026-04-03",
        request_id: request.request_id,
        result: {
          solver_name: "greedy_dispatch",
          status: "feasible",
          assignments: [],
          objective: {},
          duration_ms: 1,
          metadata: {
            portfolio: {
              solver_config: "GREED",
            },
          },
          random_seed: null,
        },
      };
    },
    async executeRepairRequest(): Promise<unknown> {
      throw new Error("unused");
    },
  };

  const app = buildControlPlaneApp({ executor });
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: createSolveRequest(),
  });

  assert.equal(response.statusCode, 200);
  const payload = response.json() as { request_id: string; result: { solver_name: string } };
  assert.equal(payload.result.solver_name, "greedy_dispatch");
  assert.equal(payload.request_id, seenRequestId);
  assert.ok(typeof seenRequestId === "string" && seenRequestId.length > 0);

  await app.close();
});

test("solve route rejects invalid upstream response", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        return { invalid: true };
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: createSolveRequest(),
  });

  assert.equal(response.statusCode, 502);
  const payload = response.json() as { error: string };
  assert.equal(payload.error, "Bad Gateway");

  await app.close();
});