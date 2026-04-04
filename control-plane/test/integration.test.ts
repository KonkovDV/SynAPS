import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { buildControlPlaneApp } from "../src/app";
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

function createSolveRequest(problem: unknown): Record<string, unknown> {
  return {
    contract_version: "2026-04-03",
    problem,
    context: {
      regime: "nominal",
      exact_required: false,
      preferred_max_latency_s: null,
    },
    verify_feasibility: true,
    solve_options: {},
  };
}

test("control-plane solve route executes the real Python kernel", async () => {
  const app = buildControlPlaneApp();
  const problem = loadTinyProblem();

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: createSolveRequest(problem),
  });

  assert.equal(response.statusCode, 200);
  const payload = response.json() as {
    result: {
      status: string;
      metadata: {
        portfolio: {
          solver_config: string;
          verified_feasible: boolean;
        };
      };
    };
  };
  assert.ok(["feasible", "optimal"].includes(payload.result.status));
  assert.equal(payload.result.metadata.portfolio.verified_feasible, true);
  assert.ok(payload.result.metadata.portfolio.solver_config.length > 0);

  await app.close();
});

test("control-plane repair route executes the real Python kernel", async () => {
  const app = buildControlPlaneApp();
  const problem = loadTinyProblem();

  const solveResponse = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: createSolveRequest(problem),
  });

  assert.equal(solveResponse.statusCode, 200);
  const solvePayload = solveResponse.json() as {
    result: {
      assignments: Array<{ operation_id: string }>;
    };
  };
  assert.ok(solvePayload.result.assignments.length > 0);

  const disruptedOperationId = solvePayload.result.assignments[0].operation_id;
  const repairResponse = await app.inject({
    method: "POST",
    url: "/api/v1/repair",
    payload: {
      contract_version: "2026-04-03",
      problem,
      base_assignments: solvePayload.result.assignments,
      disrupted_op_ids: [disruptedOperationId],
      radius: 2,
      regime: "breakdown",
      verify_feasibility: true,
    },
  });

  assert.equal(repairResponse.statusCode, 200);
  const repairPayload = repairResponse.json() as {
    result: {
      status: string;
      metadata: {
        portfolio: {
          solver_config: string;
          verified_feasible: boolean;
        };
      };
    };
  };
  assert.ok(["feasible", "optimal"].includes(repairPayload.result.status));
  assert.equal(repairPayload.result.metadata.portfolio.solver_config, "INCREMENTAL_REPAIR");
  assert.equal(repairPayload.result.metadata.portfolio.verified_feasible, true);

  await app.close();
});