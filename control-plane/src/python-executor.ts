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

function resolveExecutionLimits(): SynapsPythonExecutionLimits {
  const timeoutMs = Number(process.env.SYNAPS_PYTHON_EXEC_TIMEOUT_MS ?? 0);
  const maxOutputBytes = Number(process.env.SYNAPS_PYTHON_MAX_OUTPUT_BYTES ?? 5_000_000);

  return {
    timeoutMs: Number.isFinite(timeoutMs) && timeoutMs > 0 ? Math.floor(timeoutMs) : 0,
    maxOutputBytes:
      Number.isFinite(maxOutputBytes) && maxOutputBytes > 0
        ? Math.floor(maxOutputBytes)
        : 5_000_000,
  };
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
        ["-m", "synaps", subcommand, "-", "--output-file", responsePath],
        {
          cwd: paths.repoRoot,
          env: process.env,
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
              child.kill();
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

    const responseText = await fs.readFile(responsePath, "utf-8");

    try {
      return JSON.parse(responseText) as unknown;
    } catch (parseError) {
      throw new SynapsPythonBridgeError(
        `Python bridge returned non-JSON payload for ${subcommand}: ${String(parseError)}`,
        stderr || responseText,
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