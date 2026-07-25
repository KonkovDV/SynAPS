import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import {
  AdmissionError,
  admitInlineProblem,
  admitSolvePayload,
  classifySolverConfig,
  resolveAdmissionLimits,
} from "../src/admission";
import { applyAclGuardrails, AclValidationError } from "../src/anti-corruption";
import { buildControlPlaneApp } from "../src/app";
import { _testInternals } from "../src/python-executor";
import { resolveSynapsRepoRoot } from "../src/paths";

function loadTinyProblem(): Record<string, unknown> {
  const filePath = path.join(
    resolveSynapsRepoRoot(process.cwd()),
    "benchmark",
    "instances",
    "tiny_3x3.json",
  );
  return JSON.parse(fs.readFileSync(filePath, "utf-8")) as Record<string, unknown>;
}

test("classifySolverConfig maps exact and heavy families", () => {
  assert.equal(classifySolverConfig("CPSAT-30"), "exact");
  assert.equal(classifySolverConfig("LBBD-10"), "exact");
  assert.equal(classifySolverConfig("RHC-ALNS"), "heavy_metaheuristic");
  assert.equal(classifySolverConfig("RHC-GREEDY-COVER"), "constructive");
  assert.equal(classifySolverConfig("GREED"), "constructive");
});

test("admitInlineProblem rejects oversized operation counts", () => {
  const problem = loadTinyProblem();
  const ops = problem.operations as unknown[];
  problem.operations = Array.from({ length: 20 }, (_, index) => ({
    ...(ops[0] as object),
    id: `d0000001-0001-4001-8001-${String(index).padStart(12, "0")}`,
  }));

  assert.throws(
    () =>
      admitInlineProblem(problem, "GREED", resolveAdmissionLimits({ maxOperations: 10 })),
    (error: unknown) => error instanceof AdmissionError,
  );
});

test("admitSolvePayload rejects exact solvers above exact op cap", () => {
  const problem = loadTinyProblem();
  const ops = problem.operations as unknown[];
  problem.operations = Array.from({ length: 80 }, (_, index) => ({
    ...(ops[0] as object),
    id: `d0000001-0001-4001-8001-${String(index).padStart(12, "0")}`,
  }));

  assert.throws(
    () =>
      admitSolvePayload(
        { problem, solver_config: "CPSAT-30" },
        resolveAdmissionLimits({ exactSolverMaxOperations: 50, maxOperations: 10_000 }),
      ),
    (error: unknown) =>
      error instanceof AdmissionError && error.issues[0]?.code === "SOLVER_OPS_ADMISSION",
  );
});

test("ACL setup cube budget rejects combinatorial SDST blowups", () => {
  const problem = loadTinyProblem();
  problem.states = Array.from({ length: 40 }, (_, index) => ({
    id: `a0000001-0001-4001-8001-${String(index).padStart(12, "0")}`,
    code: `S${index}`,
    label: `State ${index}`,
  }));
  problem.work_centers = Array.from({ length: 40 }, (_, index) => ({
    id: `c0000001-0001-4001-8001-${String(index).padStart(12, "0")}`,
    code: `WC${index}`,
    capability_group: "machining",
    speed_factor: 1.0,
    max_parallel: 1,
  }));
  problem.setup_matrix = [];

  assert.throws(
    () => applyAclGuardrails(problem),
    (error: unknown) =>
      error instanceof AclValidationError && error.issues[0]?.code === "SETUP_CUBE_BUDGET",
  );
});

test("INSTANCE_DIR refuses repository root mounts", () => {
  const previous = process.env.SYNAPS_INSTANCE_DIR;
  const repoRoot = resolveSynapsRepoRoot(process.cwd());
  process.env.SYNAPS_INSTANCE_DIR = repoRoot;
  try {
    assert.throws(() => _testInternals.resolveInstanceDir(repoRoot), /strictly under/);
  } finally {
    if (previous === undefined) {
      delete process.env.SYNAPS_INSTANCE_DIR;
    } else {
      process.env.SYNAPS_INSTANCE_DIR = previous;
    }
  }
});

test("metrics are private without auth unless PUBLIC_METRICS", async () => {
  const app = buildControlPlaneApp({
    rateLimit: null,
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });
  const hidden = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(hidden.statusCode, 404);
  await app.close();

  const open = buildControlPlaneApp({
    rateLimit: null,
    publicMetrics: true,
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        throw new Error("unused");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });
  const visible = await open.inject({ method: "GET", url: "/metrics" });
  assert.equal(visible.statusCode, 200);
  await open.close();
});

test("solve route rejects oversize problems before Python spawn", async () => {
  const problem = loadTinyProblem();
  const ops = problem.operations as unknown[];
  problem.operations = Array.from({ length: 30 }, (_, index) => ({
    ...(ops[0] as object),
    id: `d0000001-0001-4001-8001-${String(index).padStart(12, "0")}`,
  }));

  let spawned = false;
  const app = buildControlPlaneApp({
    rateLimit: null,
    admissionLimits: { maxOperations: 10 },
    executor: {
      async executeSolveRequest(): Promise<unknown> {
        spawned = true;
        throw new Error("should not spawn");
      },
      async executeRepairRequest(): Promise<unknown> {
        throw new Error("unused");
      },
    },
  });

  const response = await app.inject({
    method: "POST",
    url: "/api/v1/solve",
    payload: {
      contract_version: "2026-04-03",
      problem,
      context: { regime: "nominal", exact_required: false, preferred_max_latency_s: null },
      verify_feasibility: true,
      solve_options: {},
      solver_config: "GREED",
    },
  });

  assert.equal(response.statusCode, 422);
  assert.equal(spawned, false);
  await app.close();
});

test("python bridge defaults memory limit under BFF", () => {
  const env = _testInternals.buildPythonBridgeEnv({
    PATH: "bin",
  });
  assert.equal(env.SYNAPS_SOLVE_MEMORY_LIMIT_MB, "4096");
});
