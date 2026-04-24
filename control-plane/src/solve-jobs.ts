import { randomUUID } from "node:crypto";

export type SolveJobStatus = "pending" | "running" | "succeeded" | "failed";

export interface SolveJobError {
  statusCode: number;
  error: string;
  message: string;
  errors?: unknown;
  bridge_code?: string;
}

export interface SolveJobRecord {
  job_id: string;
  request_id: string;
  status: SolveJobStatus;
  status_url: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  result: Record<string, unknown> | null;
  error: SolveJobError | null;
}

export interface EnqueueSolveJobOptions {
  requestId: string;
  statusUrlBase: string;
  run: () => Promise<Record<string, unknown>>;
  serializeError: (error: unknown) => SolveJobError;
}

export interface SynapsSolveJobStore {
  enqueueSolveJob(options: EnqueueSolveJobOptions): SolveJobRecord;
  getSolveJob(jobId: string): SolveJobRecord | null;
}

function cloneSolveJobRecord(record: SolveJobRecord): SolveJobRecord {
  return {
    ...record,
    result: record.result ? structuredClone(record.result) : null,
    error: record.error ? { ...record.error } : null,
  };
}

export class InMemorySolveJobStore implements SynapsSolveJobStore {
  private readonly jobs = new Map<string, SolveJobRecord>();

  enqueueSolveJob(options: EnqueueSolveJobOptions): SolveJobRecord {
    const jobId = randomUUID();
    const now = new Date().toISOString();
    const record: SolveJobRecord = {
      job_id: jobId,
      request_id: options.requestId,
      status: "pending",
      status_url: `${options.statusUrlBase}/${jobId}`,
      created_at: now,
      started_at: null,
      completed_at: null,
      result: null,
      error: null,
    };
    this.jobs.set(jobId, record);

    setImmediate(() => {
      void this.runJob(jobId, options);
    });

    return cloneSolveJobRecord(record);
  }

  getSolveJob(jobId: string): SolveJobRecord | null {
    const record = this.jobs.get(jobId);
    return record ? cloneSolveJobRecord(record) : null;
  }

  private async runJob(jobId: string, options: EnqueueSolveJobOptions): Promise<void> {
    const record = this.jobs.get(jobId);
    if (!record) {
      return;
    }

    record.status = "running";
    record.started_at = new Date().toISOString();
    try {
      record.result = await options.run();
      record.status = "succeeded";
      record.error = null;
    } catch (error) {
      record.status = "failed";
      record.result = null;
      record.error = options.serializeError(error);
    } finally {
      record.completed_at = new Date().toISOString();
    }
  }
}