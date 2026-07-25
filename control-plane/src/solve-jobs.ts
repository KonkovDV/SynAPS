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
  tenant_id: string | null;
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
  tenantId: string | null;
  statusUrlBase: string;
  run: () => Promise<Record<string, unknown>>;
  serializeError: (error: unknown) => SolveJobError;
}

export interface SynapsSolveJobStore {
  enqueueSolveJob(options: EnqueueSolveJobOptions): SolveJobRecord;
  getSolveJob(jobId: string): SolveJobRecord | null;
}

export interface InMemorySolveJobStoreOptions {
  maxJobs?: number;
  maxInflight?: number;
  ttlMs?: number;
}

export class SolveJobCapacityError extends Error {
  readonly statusCode = 429;

  constructor(message: string) {
    super(message);
    this.name = "SolveJobCapacityError";
  }
}

function cloneSolveJobRecord(record: SolveJobRecord): SolveJobRecord {
  return {
    ...record,
    result: record.result ? structuredClone(record.result) : null,
    error: record.error ? { ...record.error } : null,
  };
}

const DEFAULT_MAX_JOBS = 256;
const DEFAULT_MAX_INFLIGHT = 4;
const DEFAULT_TTL_MS = 60 * 60 * 1000;

export class InMemorySolveJobStore implements SynapsSolveJobStore {
  private readonly jobs = new Map<string, SolveJobRecord>();
  private readonly maxJobs: number;
  private readonly maxInflight: number;
  private readonly ttlMs: number;
  private inflight = 0;

  constructor(options: InMemorySolveJobStoreOptions = {}) {
    this.maxJobs = options.maxJobs ?? DEFAULT_MAX_JOBS;
    this.maxInflight = options.maxInflight ?? DEFAULT_MAX_INFLIGHT;
    this.ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
  }

  enqueueSolveJob(options: EnqueueSolveJobOptions): SolveJobRecord {
    this.evictExpired();

    if (this.inflight >= this.maxInflight) {
      throw new SolveJobCapacityError(
        `Solve job inflight limit reached (${this.maxInflight})`,
      );
    }
    if (this.jobs.size >= this.maxJobs) {
      throw new SolveJobCapacityError(`Solve job store capacity reached (${this.maxJobs})`);
    }

    const jobId = randomUUID();
    const now = new Date().toISOString();
    const record: SolveJobRecord = {
      job_id: jobId,
      request_id: options.requestId,
      tenant_id: options.tenantId,
      status: "pending",
      status_url: `${options.statusUrlBase}/${jobId}`,
      created_at: now,
      started_at: null,
      completed_at: null,
      result: null,
      error: null,
    };
    this.jobs.set(jobId, record);
    this.inflight += 1;

    setImmediate(() => {
      void this.runJob(jobId, options);
    });

    return cloneSolveJobRecord(record);
  }

  getSolveJob(jobId: string): SolveJobRecord | null {
    this.evictExpired();
    const record = this.jobs.get(jobId);
    return record ? cloneSolveJobRecord(record) : null;
  }

  private evictExpired(): void {
    if (this.ttlMs <= 0) {
      return;
    }
    const cutoff = Date.now() - this.ttlMs;
    for (const [jobId, record] of this.jobs) {
      const anchor = Date.parse(record.completed_at ?? record.created_at);
      if (!Number.isFinite(anchor) || anchor > cutoff) {
        continue;
      }
      if (record.status === "pending" || record.status === "running") {
        continue;
      }
      this.jobs.delete(jobId);
    }
  }

  private async runJob(jobId: string, options: EnqueueSolveJobOptions): Promise<void> {
    const record = this.jobs.get(jobId);
    if (!record) {
      this.inflight = Math.max(0, this.inflight - 1);
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
      this.inflight = Math.max(0, this.inflight - 1);
    }
  }
}
