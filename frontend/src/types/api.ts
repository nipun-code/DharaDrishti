/** Types mirroring the backend's Pydantic schemas (app/schemas). */

export type DependencyStatus = "ok" | "error";

export interface DependencyCheck {
  status: DependencyStatus;
  latency_ms: number;
  error: string | null;
}

export interface ReadinessResponse {
  status: "ok" | "unavailable";
  checks: Record<string, DependencyCheck>;
}

export interface ErrorBody {
  code: string;
  message: string;
  request_id: string | null;
  details?: unknown;
}

export interface ErrorResponse {
  error: ErrorBody;
}
