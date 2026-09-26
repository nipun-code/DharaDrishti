/** The single typed API client. All backend calls go through here. */

import type { ErrorResponse, ReadinessResponse } from "../types/api";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ErrorResponse).error?.code === "string"
  );
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

interface RequestOptions extends RequestInit {
  /** Extra non-2xx statuses whose body is a valid payload (e.g. 503 from /health/ready). */
  acceptStatuses?: number[];
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { acceptStatuses = [], headers, ...init } = options;
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...headers },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server.", null);
  }

  const body = await parseJson(response);
  if (response.ok || acceptStatuses.includes(response.status)) {
    return body as T;
  }
  const requestId = response.headers.get("X-Request-ID");
  if (isErrorResponse(body)) {
    const { code, message, request_id } = body.error;
    throw new ApiError(response.status, code, message, request_id ?? requestId);
  }
  throw new ApiError(response.status, "http_error", response.statusText || "Request failed.", requestId);
}

export const api = {
  getReadiness: (signal?: AbortSignal) =>
    request<ReadinessResponse>("/health/ready", { signal, acceptStatuses: [503] }),
};
