import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { setImmediate as delayImmediate } from "node:timers/promises";

import { buildControlPlaneApp } from "../src/app";
import {
  SynapsPythonBridgeError,
  type SynapsContractExecutor,
} from "../src/python-executor";
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
      get?: {
        parameters?: Array<{ name: string }>;
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
  assert.ok(payload.routes.includes("/api/v1/solve/jobs"));
  assert.ok(payload.routes.includes("/api/v1/solve/jobs/:jobId"));
  assert.ok(payload.routes.includes("/metrics"));
  assert.ok(payload.routes.includes("/api/v1/ui/gantt-model"));

  await app.close();
});

test("metrics endpoint exposes Prometheus series", async () => {
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

  const response = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(response.statusCode, 200);
  assert.match(response.body, /synaps_solve_duration_seconds_bucket/);
  assert.match(response.body, /synaps_solver_runs_total/);
  assert.match(response.body, /synaps_limit_guard_transitions_total/);
  assert.match(response.body, /synaps_bridge_errors_total/);
  assert.match(response.body, /synaps_feasibility_violations_total/);
  assert.match(response.body, /synaps_active_windows_gauge/);
  assert.match(response.body, /synaps_gap_ratio/);

  await app.close();
});

test("metrics endpoint records violation kinds from portfolio metadata", async () => {
  const app = buildControlPlaneApp({
    executor: {
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
            duration_ms: 2,
            metadata: {
              portfolio: {
                solver_config: "GREED",
                violation_count: 4,
                violation_kind_counts: {
                  PRECEDENCE_VIOLATION: 3,
                  MACHINE_OVERLAP: 1,
                },
              },
            },
            random_seed: null,
          },
        };
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const solveResponse = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: createSolveRequest(),
  });
  assert.equal(solveResponse.statusCode, 200);

  const response = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(response.statusCode, 200);
  assert.match(
    response.body,
    /synaps_feasibility_violations_total\{kind="precedence"\} 3/,
  );
  assert.match(
    response.body,
    /synaps_feasibility_violations_total\{kind="overlap"\} 1/,
  );
  assert.match(
    response.body,
    /synaps_solver_runs_total\{solver_config="GREED",status="feasible"\} 1/,
  );

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
  assert.equal(
    payload.paths["/api/v1/solve/jobs"].post?.requestBody.content["application/json"].schema.$ref,
    "#/components/schemas/SolveRequest",
  );
  assert.equal(payload.paths["/api/v1/solve/jobs/{jobId}"].get?.parameters?.[0]?.name, "jobId");

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
  const request = createSolveRequest();
  request.solver_config = "CPSAT-30";

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: request,
  });

  assert.equal(response.statusCode, 200);
  const payload = response.json() as { request_id: string; result: { solver_name: string } };
  assert.equal(payload.result.solver_name, "greedy_dispatch");
  assert.equal(payload.request_id, seenRequestId);
  assert.ok(typeof seenRequestId === "string" && seenRequestId.length > 0);

  await app.close();
});

test("async solve job route accepts work and exposes polling status", async () => {
  let releaseSolve: (() => void) | undefined;
  const executor: SynapsContractExecutor = {
    async executeSolveRequest(payload: object): Promise<unknown> {
      const request = payload as { request_id?: string };
      await new Promise<void>((resolve) => {
        releaseSolve = resolve;
      });
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
  const createResponse = await app.inject({
    method: "POST",
    url: "/api/v1/solve/jobs",
    payload: createSolveRequest(),
  });

  assert.equal(createResponse.statusCode, 202);
  const accepted = createResponse.json() as {
    job_id: string;
    request_id: string;
    status: string;
    status_url: string;
  };
  assert.ok(accepted.job_id.length > 0);
  assert.equal(accepted.status, "pending");
  assert.equal(accepted.status_url, `/api/v1/solve/jobs/${accepted.job_id}`);

  await delayImmediate();
  const runningResponse = await app.inject({
    method: "GET",
    url: accepted.status_url,
  });
  assert.equal(runningResponse.statusCode, 200);
  const running = runningResponse.json() as { status: string; result: unknown };
  assert.equal(running.status, "running");
  assert.equal(running.result, null);

  releaseSolve?.();
  let doneResponse = await app.inject({
    method: "GET",
    url: accepted.status_url,
  });
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const payload = doneResponse.json() as { status: string };
    if (payload.status === "succeeded") {
      break;
    }
    await delayImmediate();
    doneResponse = await app.inject({
      method: "GET",
      url: accepted.status_url,
    });
  }

  assert.equal(doneResponse.statusCode, 200);
  const done = doneResponse.json() as {
    status: string;
    request_id: string;
    result: { result: { solver_name: string } };
  };
  assert.equal(done.status, "succeeded");
  assert.equal(done.request_id, accepted.request_id);
  assert.equal(done.result.result.solver_name, "greedy_dispatch");

  await app.close();
});

test("async solve job status returns 404 for unknown job", async () => {
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
    method: "GET",
    url: "/api/v1/solve/jobs/missing-job",
  });

  assert.equal(response.statusCode, 404);
  const payload = response.json() as { error: string };
  assert.equal(payload.error, "Not Found");

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

test("solve route applies limit-guard fallback after timeout", async () => {
  let attempts = 0;
  const executor: SynapsContractExecutor = {
    async executeSolveRequest(payload: object): Promise<unknown> {
      attempts += 1;
      const request = payload as { request_id?: string };

      if (attempts === 1) {
        throw new SynapsPythonBridgeError("synthetic timeout", "", "timeout");
      }

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
  const payload = response.json() as {
    result: {
      metadata: {
        limit_guard?: {
          applied: boolean;
          attempts: unknown[];
        };
      };
    };
  };
  assert.ok(payload.result.metadata.limit_guard?.applied);
  assert.ok((payload.result.metadata.limit_guard?.attempts ?? []).length >= 1);
  assert.ok(attempts >= 2);

  const metrics = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(metrics.statusCode, 200);
  assert.match(
    metrics.body,
    /synaps_bridge_errors_total\{solver_config="AUTO",code="timeout"\} 1/,
  );
  assert.match(
    metrics.body,
    /synaps_limit_guard_transitions_total\{from_solver="AUTO",to_solver="CPSAT-30",reason="bridge_timeout"\} 1/,
  );

  await app.close();
});

test("solve route records status-based fallback transition metrics", async () => {
  let attempts = 0;
  const executor: SynapsContractExecutor = {
    async executeSolveRequest(payload: object): Promise<unknown> {
      attempts += 1;
      const request = payload as { request_id?: string; solver_config?: string };

      if (attempts === 1) {
        return {
          contract_version: "2026-04-03",
          request_id: request.request_id,
          result: {
            solver_name: "cpsat_solver",
            status: "timeout",
            assignments: [],
            objective: {},
            duration_ms: 1,
            metadata: {
              portfolio: {
                solver_config: request.solver_config ?? "CPSAT-30",
              },
            },
            random_seed: null,
          },
        };
      }

      return {
        contract_version: "2026-04-03",
        request_id: request.request_id,
        result: {
          solver_name: "lbbd_solver",
          status: "feasible",
          assignments: [],
          objective: {},
          duration_ms: 1,
          metadata: {
            portfolio: {
              solver_config: request.solver_config ?? "LBBD-10",
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
  const request = createSolveRequest();
  request.solver_config = "CPSAT-30";

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: request,
  });

  assert.equal(response.statusCode, 200);
  assert.equal(attempts, 2);

  const metrics = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(metrics.statusCode, 200);
  assert.match(
    metrics.body,
    /synaps_limit_guard_transitions_total\{from_solver="CPSAT-30",to_solver="LBBD-10",reason="status_timeout"\} 1/,
  );
  assert.match(
    metrics.body,
    /synaps_solver_runs_total\{solver_config="CPSAT-30",status="timeout"\} 1/,
  );
  assert.match(
    metrics.body,
    /synaps_solver_runs_total\{solver_config="LBBD-10",status="feasible"\} 1/,
  );

  await app.close();
});

test("solve route rejects cyclic precedence via ACL guardrails", async () => {
  const app = buildControlPlaneApp({
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("executor should not be called on ACL failure");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const cyclicRequest = createSolveRequest();
  const problem = cyclicRequest.problem as {
    operations: Array<{ predecessor_op_id: string | null; id: string }>;
  };
  if (problem.operations.length >= 2) {
    problem.operations[0].predecessor_op_id = problem.operations[1].id;
    problem.operations[1].predecessor_op_id = problem.operations[0].id;
  }

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: cyclicRequest,
  });

  assert.equal(response.statusCode, 422);
  const payload = response.json() as { error: string };
  assert.equal(payload.error, "Unprocessable Entity");

  await app.close();
});

test("gantt-model endpoint returns lanes and deltas", async () => {
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

  const problem = loadTinyProblem() as {
    operations: Array<Record<string, unknown>>;
    work_centers: Array<Record<string, unknown>>;
  };
  const operation = problem.operations[0];
  const workCenter = problem.work_centers[0];
  const operationId = String(operation.id);
  const workCenterId = String(workCenter.id);

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/ui/gantt-model",
    payload: {
      problem,
      schedule: {
        assignments: [
          {
            operation_id: operationId,
            work_center_id: workCenterId,
            start_time: "2026-04-01T08:00:00.000Z",
            end_time: "2026-04-01T09:00:00.000Z",
          },
        ],
      },
      baseline_schedule: {
        assignments: [
          {
            operation_id: operationId,
            work_center_id: workCenterId,
            start_time: "2026-04-01T07:30:00.000Z",
            end_time: "2026-04-01T08:30:00.000Z",
          },
        ],
      },
    },
  });

  assert.equal(response.statusCode, 200);
  const payload = response.json() as {
    lanes: unknown[];
    deltas: unknown[];
    summary: { operations: number };
  };
  assert.ok(payload.lanes.length >= 1);
  assert.ok(payload.summary.operations >= 1);
  assert.ok(payload.deltas.length >= 1);

  await app.close();
});