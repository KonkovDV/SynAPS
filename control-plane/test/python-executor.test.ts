import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { _testInternals, createPythonContractExecutor } from "../src/python-executor";
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

test("python executor supports file-backed solve requests with pre-validation slicing", async () => {
  const executor = createPythonContractExecutor();
  const response = await executor.executeSolveRequest({
    contract_version: "2026-04-03",
    request_id: "executor-test-instance-ref",
    problem_instance_ref: "tiny_3x3.json",
    problem_slice: {
      max_operations: 2,
    },
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
      assignments: Array<unknown>;
    };
  };

  assert.equal(response.contract_version, "2026-04-03");
  assert.equal(response.request_id, "executor-test-instance-ref");
  assert.equal(response.result.solver_name, "greedy_dispatch");
  assert.equal(response.result.assignments.length, 2);
  assert.ok(["feasible", "optimal"].includes(response.result.status));
});

test("python bridge environment allowlist keeps SynAPS and runtime variables only", () => {
  const env = _testInternals.buildPythonBridgeEnv({
    PATH: "bin",
    PYTHONPATH: "repo",
    SYNAPS_PYTHON_EXEC_TIMEOUT_MS: "1000",
    SYNAPS_DISABLE_NATIVE_ACCELERATION: "1",
    SYNAPS_CONTROL_PLANE_API_KEY: "control-plane-secret",
    SYNAPS_CONTROL_PLANE_RATE_LIMIT_MAX: "10",
    OTEL_SERVICE_NAME: "synaps-control-plane",
    AWS_SECRET_ACCESS_KEY: "secret",
    DATABASE_URL: "postgres://secret",
  });

  assert.equal(env.PATH, "bin");
  assert.equal(env.PYTHONPATH, undefined);
  assert.equal(env.PYTHONNOUSERSITE, "1");
  assert.equal(env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS, "1000");
  assert.equal(env.SYNAPS_DISABLE_NATIVE_ACCELERATION, "1");
  assert.equal(env.SYNAPS_ENABLE_RESOURCE_GUARDS, "1");
  assert.equal(env.SYNAPS_RESOURCE_GUARDS_FAIL_OPEN, "0");
  assert.ok(Number(env.SYNAPS_SOLVE_TIMEOUT_S) > 0);
  assert.equal(env.SYNAPS_CONTROL_PLANE_API_KEY, undefined);
  assert.equal(env.SYNAPS_CONTROL_PLANE_RATE_LIMIT_MAX, undefined);
  assert.equal(env.OTEL_SERVICE_NAME, "synaps-control-plane");
  assert.equal(env.AWS_SECRET_ACCESS_KEY, undefined);
  assert.equal(env.DATABASE_URL, undefined);
});

test("python bridge can opt into PYTHONPATH inheritance", () => {
  const env = _testInternals.buildPythonBridgeEnv({
    PATH: "bin",
    PYTHONPATH: "repo",
    SYNAPS_ALLOW_PYTHONPATH: "1",
  });
  assert.equal(env.PYTHONPATH, "repo");
});

test("python bridge defaults to a positive execution timeout", () => {
  const previous = process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS;
  delete process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS;
  try {
    const limits = _testInternals.resolveExecutionLimits();
    assert.ok(limits.timeoutMs > 0);
    assert.equal(limits.timeoutMs, 300_000);
  } finally {
    if (previous === undefined) {
      delete process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS;
    } else {
      process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS = previous;
    }
  }
});

test("python bridge refuses TIMEOUT_MS=0 without explicit unlimited opt-in", () => {
  const previousTimeout = process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS;
  const previousAllow = process.env.SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT;
  process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS = "0";
  delete process.env.SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT;
  try {
    const limited = _testInternals.resolveExecutionLimits();
    assert.equal(limited.timeoutMs, 300_000);

    process.env.SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT = "1";
    const unlimited = _testInternals.resolveExecutionLimits();
    assert.equal(unlimited.timeoutMs, 0);
  } finally {
    if (previousTimeout === undefined) {
      delete process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS;
    } else {
      process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS = previousTimeout;
    }
    if (previousAllow === undefined) {
      delete process.env.SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT;
    } else {
      process.env.SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT = previousAllow;
    }
  }
});

test("python bridge instance dir defaults under benchmark/instances", () => {
  const previous = process.env.SYNAPS_INSTANCE_DIR;
  delete process.env.SYNAPS_INSTANCE_DIR;
  try {
    const repoRoot = resolveSynapsRepoRoot(process.cwd());
    const instanceDir = _testInternals.resolveInstanceDir(repoRoot);
    assert.equal(instanceDir, path.join(repoRoot, "benchmark", "instances"));
  } finally {
    if (previous === undefined) {
      delete process.env.SYNAPS_INSTANCE_DIR;
    } else {
      process.env.SYNAPS_INSTANCE_DIR = previous;
    }
  }
});
