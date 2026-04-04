import fs from "node:fs";
import path from "node:path";

import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020";
import addFormats from "ajv-formats";

import { resolveRuntimePaths } from "./paths";

export interface SynapsContractSchemas {
  solveRequest: object;
  solveResponse: object;
  repairRequest: object;
  repairResponse: object;
}

export interface SynapsContractValidators {
  solveRequest: ValidateFunction;
  solveResponse: ValidateFunction;
  repairRequest: ValidateFunction;
  repairResponse: ValidateFunction;
}

export interface ValidationFailure {
  message: string;
  errors: ErrorObject[];
}

function readJsonSchema(schemaPath: string): object {
  return JSON.parse(fs.readFileSync(schemaPath, "utf-8")) as object;
}

export function loadContractSchemas(startDir = process.cwd()): SynapsContractSchemas {
  const { contractSchemaDir } = resolveRuntimePaths(startDir);

  return {
    solveRequest: readJsonSchema(path.join(contractSchemaDir, "solve-request.schema.json")),
    solveResponse: readJsonSchema(path.join(contractSchemaDir, "solve-response.schema.json")),
    repairRequest: readJsonSchema(path.join(contractSchemaDir, "repair-request.schema.json")),
    repairResponse: readJsonSchema(path.join(contractSchemaDir, "repair-response.schema.json")),
  };
}

export function buildContractValidators(
  schemas: SynapsContractSchemas,
): SynapsContractValidators {
  const ajv = new Ajv2020({ strict: false, allErrors: false });
  addFormats(ajv);

  return {
    solveRequest: ajv.compile(schemas.solveRequest),
    solveResponse: ajv.compile(schemas.solveResponse),
    repairRequest: ajv.compile(schemas.repairRequest),
    repairResponse: ajv.compile(schemas.repairResponse),
  };
}

export function collectValidationFailure(
  validator: ValidateFunction,
  message: string,
): ValidationFailure {
  return {
    message,
    errors: (validator.errors ?? []) as ErrorObject[],
  };
}

export function withRequestId<T extends Record<string, unknown>>(
  payload: T,
  requestId: string,
): T {
  if (typeof payload.request_id === "string" && payload.request_id.length > 0) {
    return payload;
  }

  return {
    ...payload,
    request_id: requestId,
  };
}