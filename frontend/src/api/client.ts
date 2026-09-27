/**
 * The single typed API client. Every backend call goes through here.
 *
 * Auth: the access token lives only in memory. The refresh token is kept in sessionStorage so
 * a page reload in the same tab stays signed in; closing the tab signs out. On a 401 the client
 * refreshes once (single-flight) and retries the request.
 */

import type {
  ActSummary,
  Citation,
  DocumentList,
  DatasetStatus,
  DocumentRead,
  ErrorBody,
  EvalConfig,
  EvalRunDetail,
  EvalRunSummary,
  ErrorResponse,
  FeedbackRead,
  MappingView,
  PipelineStage,
  QueryRequest,
  QueryResponse,
  ReadinessResponse,
  SectionView,
  StreamEvent,
  TokenResponse,
  UploadDocumentInput,
  User,
} from "../types/api";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API = `${BASE_URL}/api/v1`;
const REFRESH_KEY = "dd.refresh";

// ---------------------------------------------------------------- errors
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
    this.details = body.details;
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

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error */
  }
  if (isErrorResponse(body)) return new ApiError(response.status, body.error);
  return new ApiError(response.status, {
    code: "http_error",
    message: response.statusText || `Request failed (${response.status}).`,
    request_id: response.headers.get("X-Request-ID"),
  });
}

const NETWORK_ERROR: ErrorBody = {
  code: "network_error",
  message: "Could not reach the server. Check your connection and try again.",
  request_id: null,
};

/** A readable one-liner for toasts, including validation details when present. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "validation_error" && Array.isArray(err.details) && err.details.length) {
      const first = err.details[0] as { loc?: unknown[]; msg?: string };
      const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
      return field ? `${field}: ${first.msg ?? err.message}` : err.message;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

// ---------------------------------------------------------------- token store
type SessionListener = (signedIn: boolean) => void;

const tokens: { access: string | null; refresh: string | null } = {
  access: null,
  refresh: readRefresh(),
};
const listeners = new Set<SessionListener>();

function readRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function setTokens(pair: TokenResponse | null): void {
  tokens.access = pair?.access_token ?? null;
  tokens.refresh = pair?.refresh_token ?? null;
  try {
    if (pair) sessionStorage.setItem(REFRESH_KEY, pair.refresh_token);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage unavailable: stay in-memory only */
  }
  listeners.forEach((listener) => listener(pair !== null));
}

export function onSessionChange(listener: SessionListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function hasRefreshToken(): boolean {
  return tokens.refresh !== null;
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the refresh token for a new pair. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  if (!tokens.refresh) return Promise.resolve(false);
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh }),
      });
      if (!response.ok) {
        setTokens(null);
        return false;
      }
      setTokens((await response.json()) as TokenResponse);
      return true;
    } catch {
      return false; // network error: keep the refresh token, try again later
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

// ---------------------------------------------------------------- core request
interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  auth?: boolean;
  acceptStatuses?: number[];
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.auth !== false && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  try {
    return await fetch(path, { method: options.method ?? "GET", headers, body, signal: options.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, NETWORK_ERROR);
  }
}

/** Send with auth; on 401 refresh once and retry. */
async function authorizedFetch(path: string, options: RequestOptions): Promise<Response> {
  let response = await send(path, options);
  if (response.status === 401 && options.auth !== false && (await refreshSession())) {
    response = await send(path, options);
  }
  if (response.status === 401 && options.auth !== false) setTokens(null);
  return response;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await authorizedFetch(path, options);
  if (!response.ok && !(options.acceptStatuses ?? []).includes(response.status)) {
    throw await toApiError(response);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------------------------------------------------------------- SSE over fetch
function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

function toStreamEvent(event: string, data: string): StreamEvent | null {
  const payload = JSON.parse(data) as Record<string, unknown>;
  switch (event) {
    case "status":
      return { type: "status", stage: payload.stage as PipelineStage, message: String(payload.message) };
    case "token":
      return { type: "token", text: String(payload.text) };
    case "citations":
      return { type: "citations", citations: payload.citations as Citation[] };
    case "done":
      return { type: "done", response: payload as unknown as QueryResponse };
    case "error":
      return { type: "error", error: payload as unknown as ErrorBody };
    default:
      return null;
  }
}

/**
 * POST /query/stream, read with fetch + ReadableStream (EventSource can't send headers).
 * Resolves when the stream ends; throws ApiError for HTTP errors before the stream starts.
 */
async function streamQuery(
  body: QueryRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await authorizedFetch(`${API}/query/stream`, { method: "POST", body, signal });
  if (!response.ok) throw await toApiError(response);
  if (!response.body) throw new ApiError(0, { ...NETWORK_ERROR, message: "Streaming is not supported." });

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const parsed = parseSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (parsed) {
        const event = toStreamEvent(parsed.event, parsed.data);
        if (event) onEvent(event);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

// ---------------------------------------------------------------- endpoints
export const api = {
  health: {
    ready: (signal?: AbortSignal) =>
      request<ReadinessResponse>(`${BASE_URL}/health/ready`, { signal, auth: false, acceptStatuses: [503] }),
  },

  auth: {
    async login(email: string, password: string): Promise<void> {
      setTokens(
        await request<TokenResponse>(`${API}/auth/login`, {
          method: "POST",
          body: { email, password },
          auth: false,
        }),
      );
    },
    register: (email: string, password: string) =>
      request<User>(`${API}/auth/register`, { method: "POST", body: { email, password }, auth: false }),
    me: () => request<User>(`${API}/auth/me`),
    logout(): void {
      setTokens(null);
    },
  },

  catalog: {
    acts: () => request<ActSummary[]>(`${API}/acts`),
    section: (act: string, section: string, signal?: AbortSignal) =>
      request<SectionView>(`${API}/sections/${encodeURIComponent(act)}/${encodeURIComponent(section)}`, {
        signal,
      }),
    ipcMapping: (section: string, signal?: AbortSignal) =>
      request<MappingView>(`${API}/mapping/ipc/${encodeURIComponent(section)}`, { signal }),
  },

  query: {
    ask: (body: QueryRequest) => request<QueryResponse>(`${API}/query`, { method: "POST", body }),
    stream: streamQuery,
    feedback: (queryLogId: string, rating: 1 | -1) =>
      request<FeedbackRead>(`${API}/feedback`, {
        method: "POST",
        body: { query_log_id: queryLogId, rating },
      }),
  },

  evaluation: {
    dataset: () => request<DatasetStatus>(`${API}/eval/dataset`),
    run: (config: EvalConfig) =>
      request<{ eval_run_id: string; status: string }>(`${API}/eval/run`, { method: "POST", body: config }),
    runs: () => request<EvalRunSummary[]>(`${API}/eval/runs?limit=30`),
    get: (id: string, signal?: AbortSignal) => request<EvalRunDetail>(`${API}/eval/runs/${id}`, { signal }),
  },

  documents: {
    list: (signal?: AbortSignal) => request<DocumentList>(`${API}/documents?limit=200`, { signal }),
    get: (id: string) => request<DocumentRead>(`${API}/documents/${id}`),
    remove: (id: string) => request<void>(`${API}/documents/${id}`, { method: "DELETE" }),
    upload(input: UploadDocumentInput): Promise<{ document_id: string; status: string }> {
      const form = new FormData();
      form.append("file", input.file);
      form.append("act_short_code", input.actShortCode);
      if (input.actFullName) form.append("act_full_name", input.actFullName);
      if (input.actYear) form.append("act_year", String(input.actYear));
      if (input.actStatus) form.append("act_status", input.actStatus);
      return request(`${API}/documents`, { method: "POST", form });
    },
  },
};
