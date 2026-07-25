import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

import { resolveRuntimePaths, type SynapsRuntimePaths } from "./paths";

export interface SynapsContractExecutor {
  executeSolveRequest(payload: object): Promise<unknown>;
  executeRepairRequest(payload: object): Promise<unknown>;
}

export type SynapsPythonBridgeErrorCode = "bridge" | "timeout" | "oom" | "output_limit";

export interface SynapsPythonExecutionLimits {
  timeoutMs: number;
  maxOutputBytes: number;
}

const DEFAULT_PYTHON_EXEC_TIMEOUT_MS = 300_000;
const DEFAULT_PYTHON_MAX_OUTPUT_BYTES = 5_000_000;

function resolveExecutionLimits(): SynapsPythonExecutionLimits {
  const timeoutMs = Number(
    process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS ?? DEFAULT_PYTHON_EXEC_TIMEOUT_MS,
  );
  const maxOutputBytes = Number(
    process.env.SYNAPS_PYTHON_MAX_OUTPUT_BYTES ?? DEFAULT_PYTHON_MAX_OUTPUT_BYTES,
  );

  return {
    // 0 explicitly disables the wall-clock guard for local debugging only.
    timeoutMs: Number.isFinite(timeoutMs) && timeoutMs >= 0 ? Math.floor(timeoutMs) : DEFAULT_PYTHON_EXEC_TIMEOUT_MS,
    maxOutputBytes:
      Number.isFinite(maxOutputBytes) && maxOutputBytes > 0
        ? Math.floor(maxOutputBytes)
        : DEFAULT_PYTHON_MAX_OUTPUT_BYTES,
  };
}

function resolveInstanceDir(repoRoot: string): string {
  const configured = process.env.SYNAPS_INSTANCE_DIR?.trim();
  if (configured) {
    return path.resolve(configured);
  }
  // Default sandbox: only benchmark instances, never the whole repository.
  return path.join(repoRoot, "benchmark", "instances");
}

const ALLOWED_SYNAPS_BRIDGE_ENV_KEYS = new Set([
  "SYNAPS_DISABLE_NATIVE_ACCELERATION",
  "SYNAPS_REQUEST_ID",
  "SYNAPS_ALLOW_PYTHONPATH",
  "SYNAPS_ENABLE_RESOURCE_GUARDS",
  "SYNAPS_SOLVE_TIMEOUT_S",
  "SYNAPS_SOLVE_MEMORY_LIMIT_MB",
  "SYNAPS_RESOURCE_GUARDS_FAIL_OPEN",
  "SYNAPS_INSTANCE_DIR",
]);

function isAllowedSynapsBridgeEnvKey(key: string): boolean {
  const normalizedKey = key.toUpperCase();
  return (
    normalizedKey.startsWith("SYNAPS_PYTHON_") ||
    ALLOWED_SYNAPS_BRIDGE_ENV_KEYS.has(normalizedKey)
  );
}

function buildPythonBridgeEnv(
  source: NodeJS.ProcessEnv = process.env,
  limits: SynapsPythonExecutionLimits = resolveExecutionLimits(),
): NodeJS.ProcessEnv {
  const allowedKeys = new Set([
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "PYTHONUTF8",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONNOUSERSITE",
  ]);
  // PYTHONPATH is opt-in: inheriting it lets a compromised process env shadow synaps.
  const allowPythonPath = source.SYNAPS_ALLOW_PYTHONPATH === "1";
  if (allowPythonPath) {
    allowedKeys.add("PYTHONPATH");
  }
  const env: NodeJS.ProcessEnv = {
    PYTHONNOUSERSITE: "1",
  };
  for (const [key, value] of Object.entries(source)) {
    if (value === undefined) {
      continue;
    }
    if (
      allowedKeys.has(key.toUpperCase()) ||
      isAllowedSynapsBridgeEnvKey(key) ||
      key.startsWith("OTEL_")
    ) {
      env[key] = value;
    }
  }

  // BFF default: activate portfolio resource guards and align wall-clock with bridge timeout.
  if (env.SYNAPS_ENABLE_RESOURCE_GUARDS === undefined) {
    env.SYNAPS_ENABLE_RESOURCE_GUARDS = "1";
  }
  if (
    limits.timeoutMs > 0 &&
    (env.SYNAPS_SOLVE_TIMEOUT_S === undefined || env.SYNAPS_SOLVE_TIMEOUT_S === "")
  ) {
    env.SYNAPS_SOLVE_TIMEOUT_S = String(Math.max(1, Math.ceil(limits.timeoutMs / 1000)));
  }

  return env;
}

export class SynapsPythonBridgeError extends Error {
  readonly code: SynapsPythonBridgeErrorCode;

  constructor(
    message: string,
    readonly stderr: string,
    code: SynapsPythonBridgeErrorCode = "bridge",
  ) {
    super(message);
    this.name = "SynapsPythonBridgeError";
    this.code = code;
  }
}

function detectBridgeErrorCode(stderr: string): SynapsPythonBridgeErrorCode {
  const normalized = stderr.toLowerCase();
  if (
    normalized.includes("memoryerror") ||
    normalized.includes("out of memory") ||
    normalized.includes("oom")
  ) {
    return "oom";
  }
  return "bridge";
}

async function executePythonContract(
  paths: SynapsRuntimePaths,
  limits: SynapsPythonExecutionLimits,
  subcommand: "solve-request" | "repair-request",
  payload: object,
): Promise<unknown> {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "synaps-bff-"));
  const responsePath = path.join(tempDir, `${subcommand}.response.json`);
  const commandArgs = ["-m", "synaps", subcommand, "-", "--output-file", responsePath];
  if (subcommand === "solve-request") {
    commandArgs.push("--instance-dir", resolveInstanceDir(paths.repoRoot));
  }

  try {
    const { stdout, stderr, exitCode } = await new Promise<{
      stdout: string;
      stderr: string;
      exitCode: number;
    }>((resolve, reject) => {
      let timedOut = false;
      let outputLimitExceeded = false;
      const child = spawn(
        paths.pythonExecutable,
        commandArgs,
        {
          cwd: paths.repoRoot,
          env: buildPythonBridgeEnv(process.env, limits),
          stdio: ["pipe", "pipe", "pipe"],
        },
      );

      let stdout = "";
      let stderr = "";
      let outputBytes = 0;

      const timeoutHandle =
        limits.timeoutMs > 0
          ? setTimeout(() => {
              timedOut = true;
              try {
                child.kill();
              } catch {
                // ignore
              }
              // Escalate if the solver ignores the soft signal (OR-Tools / native).
              const escalate = setTimeout(() => {
                try {
                  child.kill("SIGKILL");
                } catch {
                  // ignore
                }
              }, 2_000);
              if (typeof escalate.unref === "function") {
                escalate.unref();
              }
            }, limits.timeoutMs)
          : null;

      const onChunk = (chunk: string): boolean => {
        outputBytes += Buffer.byteLength(chunk, "utf-8");
        if (outputBytes > limits.maxOutputBytes) {
          outputLimitExceeded = true;
          child.kill();
          return false;
        }
        return true;
      };

      child.stdout?.setEncoding("utf-8");
      child.stdout?.on("data", (chunk: string) => {
        if (!onChunk(chunk)) {
          return;
        }
        stdout += chunk;
      });

      child.stderr?.setEncoding("utf-8");
      child.stderr?.on("data", (chunk: string) => {
        if (!onChunk(chunk)) {
          return;
        }
        stderr += chunk;
      });

      child.on("error", reject);
      child.on("close", (code) => {
        if (timeoutHandle !== null) {
          clearTimeout(timeoutHandle);
        }

        if (timedOut) {
          reject(
            new SynapsPythonBridgeError(
              `Python bridge timed out for ${subcommand} after ${limits.timeoutMs}ms`,
              stderr || stdout,
              "timeout",
            ),
          );
          return;
        }

        if (outputLimitExceeded) {
          reject(
            new SynapsPythonBridgeError(
              `Python bridge exceeded output limit for ${subcommand} (${limits.maxOutputBytes} bytes)`,
              stderr || stdout,
              "output_limit",
            ),
          );
          return;
        }

        resolve({ stdout, stderr, exitCode: code ?? -1 });
      });

      child.stdin?.end(JSON.stringify(payload), "utf-8");
    });

    if (exitCode !== 0) {
      const stderrPayload = stderr || stdout;
      throw new SynapsPythonBridgeError(
        `Python bridge failed for ${subcommand} with exit code ${exitCode}`,
        stderrPayload,
        detectBridgeErrorCode(stderrPayload),
      );
    }

    const responseStat = await fs.stat(responsePath);
    if (responseStat.size > limits.maxOutputBytes) {
      throw new SynapsPythonBridgeError(
        `Python bridge response file exceeded output limit for ${subcommand} (${limits.maxOutputBytes} bytes)`,
        stderr || stdout,
        "output_limit",
      );
    }

    const responseText = await fs.readFile(responsePath, "utf-8");

    try {
      return JSON.parse(responseText) as unknown;
    } catch (parseError) {
      throw new SynapsPythonBridgeError(
        `Python bridge returned non-JSON payload for ${subcommand}: ${String(parseError)}`,
        stderr || responseText.slice(0, 2_000),
        "bridge",
      );
    }
  } catch (error) {
    if (error instanceof SynapsPythonBridgeError) {
      throw error;
    }
    const stderr = error instanceof Error && "stderr" in error ? String((error as { stderr?: unknown }).stderr ?? "") : "";
    const code =
      error instanceof SynapsPythonBridgeError
        ? error.code
        : detectBridgeErrorCode(stderr);
    throw new SynapsPythonBridgeError(
      `Python bridge failed for ${subcommand}: ${error instanceof Error ? error.message : String(error)}`,
      stderr,
      code,
    );
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

export function createPythonContractExecutor(
  paths = resolveRuntimePaths(),
  limits = resolveExecutionLimits(),
): SynapsContractExecutor {
  return {
    async executeSolveRequest(payload: object): Promise<unknown> {
      return executePythonContract(paths, limits, "solve-request", payload);
    },
    async executeRepairRequest(payload: object): Promise<unknown> {
      return executePythonContract(paths, limits, "repair-request", payload);
    },
  };
}

export const _testInternals = {
  buildPythonBridgeEnv,
  resolveExecutionLimits,
  resolveInstanceDir,
};