import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

import { resolveRuntimePaths, type SynapsRuntimePaths } from "./paths";

export interface SynapsContractExecutor {
  executeSolveRequest(payload: object): Promise<unknown>;
  executeRepairRequest(payload: object): Promise<unknown>;
}

export class SynapsPythonBridgeError extends Error {
  constructor(
    message: string,
    readonly stderr: string,
  ) {
    super(message);
    this.name = "SynapsPythonBridgeError";
  }
}

async function executePythonContract(
  paths: SynapsRuntimePaths,
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

      child.stdout?.setEncoding("utf-8");
      child.stdout?.on("data", (chunk: string) => {
        stdout += chunk;
      });

      child.stderr?.setEncoding("utf-8");
      child.stderr?.on("data", (chunk: string) => {
        stderr += chunk;
      });

      child.on("error", reject);
      child.on("close", (code) => {
        resolve({ stdout, stderr, exitCode: code ?? -1 });
      });

      child.stdin?.end(JSON.stringify(payload), "utf-8");
    });

    if (exitCode !== 0) {
      throw new SynapsPythonBridgeError(
        `Python bridge failed for ${subcommand} with exit code ${exitCode}`,
        stderr || stdout,
      );
    }

    const responseText = await fs.readFile(responsePath, "utf-8");

    try {
      return JSON.parse(responseText) as unknown;
    } catch (parseError) {
      throw new SynapsPythonBridgeError(
        `Python bridge returned non-JSON payload for ${subcommand}: ${String(parseError)}`,
        stderr || responseText,
      );
    }
  } catch (error) {
    if (error instanceof SynapsPythonBridgeError) {
      throw error;
    }
    const stderr = error instanceof Error && "stderr" in error ? String((error as { stderr?: unknown }).stderr ?? "") : "";
    throw new SynapsPythonBridgeError(
      `Python bridge failed for ${subcommand}: ${error instanceof Error ? error.message : String(error)}`,
      stderr,
    );
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

export function createPythonContractExecutor(
  paths = resolveRuntimePaths(),
): SynapsContractExecutor {
  return {
    async executeSolveRequest(payload: object): Promise<unknown> {
      return executePythonContract(paths, "solve-request", payload);
    },
    async executeRepairRequest(payload: object): Promise<unknown> {
      return executePythonContract(paths, "repair-request", payload);
    },
  };
}