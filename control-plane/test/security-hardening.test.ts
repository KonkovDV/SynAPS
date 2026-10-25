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

function feasibleExecutor(): SynapsContractExecutor {
  return {
    async executeSolveRequest(payload: object): Promise<unknown> {
      const request = payload as { request_id?: string };
      return {
        contract_version: "2026-04-03",
        request_id: request.request_id,
        result: {
          solver_name: "greedy_dispatch",
          status: "feasible",
          assignments: [],
          objective: {},
          duration_ms: 1,
          metadata: {},
          random_seed: null,
        },
      };
    },
    async executeRepairRequest(): Promise<unknown> {
      throw new Error("unused");
    },
  };
}

test("shared API key ignores spoofable x-tenant-id unless trust is enabled", async () => {
  const executor = feasibleExecutor();
  const app = buildControlPlaneApp({
    executor,
    rateLimit: null,
    apiKey: "shared-secret",
  });

  const accepted = await app.inject({
    method: "POST",
    url: "/api/v1/solve/jobs",
    headers: {
      "x-api-key": "shared-secret",
      "x-tenant-id": "spoofed-tenant",
    },
    payload: createSolveRequest(),
  });
  assert.equal(accepted.statusCode, 202);
  const { status_url: statusUrl } = accepted.json() as { status_url: string };

  const withSpoof = await app.inject({
    method: "GET",
    url: statusUrl,
    headers: {
      "x-api-key": "shared-secret",
      "x-tenant-id": "spoofed-tenant",
    },
  });
  assert.notEqual(withSpoof.statusCode, 403);
  await app.close();

  const trusted = buildControlPlaneApp({
    executor,
    rateLimit: null,
    apiKey: "shared-secret",
    trustTenantHeader: true,
  });
  const acceptedTrusted = await trusted.inject({
    method: "POST",
    url: "/api/v1/solve/jobs",
    headers: {
      "x-api-key": "shared-secret",
      "x-tenant-id": "tenant-a",
    },
    payload: createSolveRequest(),
  });
  assert.equal(acceptedTrusted.statusCode, 202);
  const trustedUrl = (acceptedTrusted.json() as { status_url: string }).status_url;

  const cross = await trusted.inject({
    method: "GET",
    url: trustedUrl,
    headers: {
      "x-api-key": "shared-secret",
      "x-tenant-id": "tenant-b",
    },
  });
  assert.equal(cross.statusCode, 403);
  await trusted.close();
});

test("API key map derives tenant identity from credential", async () => {
  const app = buildControlPlaneApp({
    executor: feasibleExecutor(),
    rateLimit: null,
    apiKeyMap: {
      "key-tenant-a": "tenant-a",
      "key-tenant-b": "tenant-b",
    },
  });

  const accepted = await app.inject({
    method: "POST",
    url: "/api/v1/solve/jobs",
    headers: { "x-api-key": "key-tenant-a" },
    payload: createSolveRequest(),
  });
  assert.equal(accepted.statusCode, 202);
  const statusUrl = (accepted.json() as { status_url: string }).status_url;

  const forbidden = await app.inject({
    method: "GET",
    url: statusUrl,
    headers: { "x-api-key": "key-tenant-b" },
  });
  assert.equal(forbidden.statusCode, 403);

  const allowed = await app.inject({
    method: "GET",
    url: statusUrl,
    headers: { "x-api-key": "key-tenant-a" },
  });
  assert.equal(allowed.statusCode, 200);

  await app.close();
});

test("solve route strips assignments when solver status is not success", async () => {
  const app = buildControlPlaneApp({
    rateLimit: null,
    executor: {
      async executeSolveRequest(payload: object): Promise<unknown> {
        const request = payload as { request_id?: string };
        return {
          contract_version: "2026-04-03",
          request_id: request.request_id,
          result: {
            solver_name: "rhc",
            status: "error",
            assignments: [
              {
                operation_id: "11111111-1111-4111-8111-111111111111",
                work_center_id: "22222222-2222-4222-8222-222222222222",
                start_time: "2026-04-01T08:00:00.000Z",
                end_time: "2026-04-01T09:00:00.000Z",
              },
            ],
            objective: {},
            duration_ms: 1,
            metadata: {},
            random_seed: null,
            error_category: "constructive_failure",
          },
        };
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
  assert.equal(response.statusCode, 200);
  const body = response.json() as {
    result: {
      status: string;
      assignments: unknown[];
      metadata: { coverage_complete: boolean; assignments_stripped: boolean };
    };
  };
  assert.equal(body.result.status, "error");
  assert.equal(body.result.assignments.length, 0);
  assert.equal(body.result.metadata.coverage_complete, false);
  assert.equal(body.result.metadata.assignments_stripped, true);

  await app.close();
});

test("rotating unverified API keys does not open fresh rate-limit buckets", async () => {
  // Anonymous loopback mode: no keys configured, so a presented key proves nothing
  // and must not choose the bucket (audit 2026-10).
  const app = buildControlPlaneApp({
    executor: feasibleExecutor(),
    rateLimit: { maxRequests: 2, windowMs: 60_000 },
    apiKey: null,
    apiKeyMap: null,
  });
  try {
    const statuses: number[] = [];
    for (let index = 0; index < 4; index += 1) {
      const response = await app.inject({
        method: "GET",
        url: "/healthz",
        headers: { "x-api-key": `${index}-forged-key` },
      });
      statuses.push(response.statusCode);
    }
    assert.deepEqual(statuses, [200, 200, 429, 429]);
  } finally {
    await app.close();
  }
});

test("private discovery routes share the client IP bucket", async () => {
  // /metrics and /openapi.json return 404 before the main limiter. Those
  // responses must still consume the IP budget (audit 2026-10, U-09).
  const app = buildControlPlaneApp({
    executor: feasibleExecutor(),
    rateLimit: { maxRequests: 2, windowMs: 60_000 },
    apiKey: null,
    apiKeyMap: null,
  });
  try {
    const statuses: number[] = [];
    for (const url of ["/metrics", "/metrics", "/openapi.json", "/openapi.json"]) {
      const response = await app.inject({ method: "GET", url });
      statuses.push(response.statusCode);
    }
    assert.deepEqual(statuses, [404, 404, 429, 429]);
  } finally {
    await app.close();
  }
});

test("failed API key attempts are rate limited per client", async () => {
  const app = buildControlPlaneApp({
    executor: feasibleExecutor(),
    rateLimit: { maxRequests: 2, windowMs: 60_000 },
    apiKey: "shared-secret",
  });
  try {
    const statuses: number[] = [];
    for (let index = 0; index < 4; index += 1) {
      const response = await app.inject({
        method: "POST",
        url: "/api/v1/solve",
        headers: { "x-api-key": `guess-${index}` },
        payload: createSolveRequest(),
      });
      statuses.push(response.statusCode);
    }
    assert.deepEqual(statuses, [401, 401, 429, 429]);
    const valid = await app.inject({
      method: "POST",
      url: "/api/v1/solve",
      headers: { "x-api-key": "shared-secret" },
      payload: createSolveRequest(),
    });
    assert.equal(valid.statusCode, 200, "a valid key keeps its own bucket");
  } finally {
    await app.close();
  }
});
