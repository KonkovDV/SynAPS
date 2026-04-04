import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { resolveRuntimePaths, type SynapsRuntimePaths } from "./paths";

const execFileAsync = promisify(execFile);

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
  const requestPath = path.join(tempDir, `${subcommand}.json`);

  try {
    await fs.writeFile(requestPath, JSON.stringify(payload, null, 2), "utf-8");
    const { stdout, stderr } = await execFileAsync(
      paths.pythonExecutable,
      ["-m", "synaps", subcommand, requestPath],
      {
        cwd: paths.repoRoot,
        env: process.env,
        maxBuffer: 10 * 1024 * 1024,
      },
    );

    try {
      return JSON.parse(stdout) as unknown;
    } catch (parseError) {
      throw new SynapsPythonBridgeError(
        `Python bridge returned non-JSON payload for ${subcommand}: ${String(parseError)}`,
        stderr,
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