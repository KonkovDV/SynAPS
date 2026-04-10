import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { createPythonContractExecutor } from "../src/python-executor";
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

test("python executor streams solve requests through the SynAPS CLI", async () => {
  const executor = createPythonContractExecutor();
  const response = await executor.executeSolveRequest({
    contract_version: "2026-04-03",
    request_id: "executor-test",
    problem: loadTinyProblem(),
    context: {
      regime: "nominal",
      exact_required: false,
      preferred_max_latency_s: 1,
    },
    solver_config: "GREED",
    verify_feasibility: true,
    solve_options: {},
  }) as {
    contract_version: string;
    request_id: string;
    result: {
      solver_name: string;
      status: string;
    };
  };

  assert.equal(response.contract_version, "2026-04-03");
  assert.equal(response.request_id, "executor-test");
  assert.equal(response.result.solver_name, "greedy_dispatch");
  assert.ok(["feasible", "optimal"].includes(response.result.status));
});