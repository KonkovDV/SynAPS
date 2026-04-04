import fs from "node:fs";
import path from "node:path";

export interface SynapsRuntimePaths {
  repoRoot: string;
  contractSchemaDir: string;
  pythonExecutable: string;
}

function directoryExists(targetPath: string): boolean {
  return fs.existsSync(targetPath) && fs.statSync(targetPath).isDirectory();
}

function fileExists(targetPath: string): boolean {
  return fs.existsSync(targetPath) && fs.statSync(targetPath).isFile();
}

export function resolveSynapsRepoRoot(startDir = process.cwd()): string {
  let currentDir = path.resolve(startDir);

  while (true) {
    const hasPyproject = fileExists(path.join(currentDir, "pyproject.toml"));
    const hasKernel = directoryExists(path.join(currentDir, "synaps"));
    const hasSchemas = directoryExists(path.join(currentDir, "schema", "contracts"));

    if (hasPyproject && hasKernel && hasSchemas) {
      return currentDir;
    }

    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) {
      throw new Error("Unable to locate SynAPS repository root from control-plane runtime");
    }
    currentDir = parentDir;
  }
}

export function resolvePythonExecutable(repoRoot: string): string {
  if (process.env.SYNAPS_PYTHON_BIN) {
    return process.env.SYNAPS_PYTHON_BIN;
  }

  let currentDir = path.resolve(repoRoot);
  while (true) {
    const windowsVenv = path.join(currentDir, ".venv", "Scripts", "python.exe");
    if (fileExists(windowsVenv)) {
      return windowsVenv;
    }

    const posixVenv = path.join(currentDir, ".venv", "bin", "python");
    if (fileExists(posixVenv)) {
      return posixVenv;
    }

    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) {
      break;
    }
    currentDir = parentDir;
  }

  return process.platform === "win32" ? "python" : "python3";
}

export function resolveRuntimePaths(startDir = process.cwd()): SynapsRuntimePaths {
  const repoRoot = resolveSynapsRepoRoot(startDir);
  return {
    repoRoot,
    contractSchemaDir: path.join(repoRoot, "schema", "contracts"),
    pythonExecutable: resolvePythonExecutable(repoRoot),
  };
}