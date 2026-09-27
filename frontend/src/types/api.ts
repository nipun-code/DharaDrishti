/** Types mirroring the backend's Pydantic schemas (backend/app/schemas). */

export type ActStatus = "in_force" | "repealed";
export type UserRole = "user" | "admin";
export type RetrievalMode = "vector" | "keyword" | "hybrid" | "hybrid_rerank";
export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

// ---- errors
export interface ErrorBody {
  code: string;
  message: string;
  request_id: string | null;
  details?: unknown;
}

export interface ErrorResponse {
  error: ErrorBody;
}

// ---- health
export interface DependencyCheck {
  status: "ok" | "error";
  latency_ms: number;
  error: string | null;
}

export interface ReadinessResponse {
  status: "ok" | "unavailable";
  checks: Record<string, DependencyCheck>;
}

// ---- auth
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  role: UserRole;
  created_at: string;
}

// ---- catalog
export interface ActSummary {
  short_code: string;
  full_name: string;
  year: number;
  status: ActStatus;
  chunks_count: number;
}

export interface SectionView {
  act: string;
  act_name: string;
  act_status: ActStatus;
  section_number: string;
  section_title: string | null;
  chapter_number: string | null;
  chapter_title: string | null;
  text: string;
  page_start: number | null;
  page_end: number | null;
}

export interface MappingTarget {
  to_act: string;
  to_section: string;
  note: string | null;
  section: SectionView | null;
}

export interface MappingView {
  from_act: string;
  from_section: string;
  source: SectionView | null;
  targets: MappingTarget[];
}

// ---- query
export interface QueryRequest {
  query: string;
  acts?: string[] | null;
  mode?: RetrievalMode;
  top_k?: number | null;
}

export interface Citation {
  n: number;
  act: string;
  act_status: ActStatus;
  section_number: string;
  section_title: string | null;
  page_start: number | null;
  snippet: string;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  refused: boolean;
  refusal_reason: string | null;
  warnings: string[];
  disclaimer: string;
  latency_ms: number;
  cache_hit: boolean;
  query_log_id: string | null;
}

export type PipelineStage = "checking" | "searching" | "reranking" | "generating" | "verifying";

export type StreamEvent =
  | { type: "status"; stage: PipelineStage; message: string }
  | { type: "token"; text: string }
  | { type: "citations"; citations: Citation[] }
  | { type: "done"; response: QueryResponse }
  | { type: "error"; error: ErrorBody };

export interface FeedbackRead {
  id: number;
  query_log_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

// ---- documents
export interface DocumentRead {
  id: string;
  act_short_code: string;
  filename: string;
  status: DocumentStatus;
  progress: number;
  error: string | null;
  pages: number | null;
  chunks_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentList {
  items: DocumentRead[];
  limit: number;
  offset: number;
}

export interface UploadDocumentInput {
  file: File;
  actShortCode: string;
  actFullName?: string;
  actYear?: number;
  actStatus?: ActStatus;
}

// ---- evaluation
export type EvalRunStatus = "pending" | "running" | "completed" | "failed";
export type EvalCategory = "exact_ref" | "semantic" | "mapping" | "out_of_scope";

export interface DatasetStatus {
  path: string;
  exists: boolean;
  questions: number;
  by_category: Partial<Record<EvalCategory, number>>;
  errors: string[];
}

export interface EvalConfig {
  modes: RetrievalMode[];
  limit: number | null;
  generation: boolean;
  use_cache?: boolean;
}

export interface ModeMetrics {
  questions: number;
  errors: number;
  recall_at_5: number | null;
  recall_at_10: number | null;
  mrr: number | null;
  retrieval_latency_p50_ms: number | null;
  retrieval_latency_p95_ms: number | null;
  faithfulness?: number | null;
  answer_relevance?: number | null;
  judged?: number;
  out_of_scope_refusal_accuracy?: number | null;
  false_refusal_rate?: number | null;
  answer_latency_p50_ms?: number | null;
  answer_latency_p95_ms?: number | null;
  avg_tokens?: number | null;
  cache_hit_rate?: number | null;
}

export interface ThresholdPoint {
  threshold: number;
  balanced_accuracy: number;
  answer_recall: number;
  refusal_recall: number;
}

export interface ThresholdReport {
  current: number;
  samples: number;
  answerable: number;
  should_refuse: number;
  recommended: number | null;
  balanced_accuracy?: number;
  answer_recall?: number;
  refusal_recall?: number;
  note?: string;
  curve: ThresholdPoint[];
}

export interface EvalMetrics {
  dataset: { questions: number; by_category: Partial<Record<EvalCategory, number>> };
  generation: boolean;
  modes: Partial<Record<RetrievalMode, ModeMetrics>>;
  threshold: ThresholdReport | null;
}

export interface EvalQuestionResult {
  id: string;
  category: EvalCategory;
  mode: RetrievalMode;
  retrieved?: string[];
  recall_at_5?: number;
  recall_at_10?: number;
  reciprocal_rank?: number;
  best_rerank_score?: number | null;
  has_direct?: boolean;
  retrieval_ms?: number;
  answer?: string;
  refused?: boolean;
  refusal_reason?: string | null;
  answer_ms?: number;
  tokens?: number | null;
  faithfulness?: number | null;
  faithfulness_note?: string | null;
  relevance?: number | null;
  relevance_note?: string | null;
  error?: string;
}

export interface EvalRunSummary {
  id: string;
  status: EvalRunStatus;
  progress: number;
  config: EvalConfig;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  headline: Partial<Record<RetrievalMode, { recall_at_5: number | null; mrr: number | null; faithfulness: number | null }>>;
}

export interface EvalRunDetail extends EvalRunSummary {
  metrics: EvalMetrics | null;
  per_question: EvalQuestionResult[] | null;
}
