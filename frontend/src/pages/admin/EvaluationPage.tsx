import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Clock,
  Database,
  FlaskConical,
  Gauge,
  History,
  Loader2,
  Play,
  Target,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { api, describeError } from "../../api/client";
import { MODE_LABELS, ModeBarChart, ThresholdChart } from "../../components/eval/EvalCharts";
import { useToast } from "../../components/Toasts";
import { EmptyState, SkeletonLines, Spinner } from "../../components/ui";
import type {
  DatasetStatus,
  EvalCategory,
  EvalRunDetail,
  EvalRunStatus,
  EvalRunSummary,
  ModeMetrics,
  RetrievalMode,
  ThresholdReport,
} from "../../types/api";

const ALL_MODES: RetrievalMode[] = ["vector", "keyword", "hybrid", "hybrid_rerank"];
const CATEGORY_LABELS: Record<EvalCategory, string> = {
  exact_ref: "Exact reference",
  semantic: "Semantic",
  mapping: "Mapping",
  out_of_scope: "Out of scope",
};
const POLL_MS = 3000;

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined, digits = 3) => (v == null ? "–" : v.toFixed(digits));
const ms = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v).toLocaleString()} ms`);
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function Section({ title, icon, children, className = "" }: { title: string; icon: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card p-5 ${className}`}>
      <h2 className="mb-4 flex items-center gap-2 font-serif text-lg font-semibold">
        <span className="text-saffron-500">{icon}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function StatusBadge({ status, progress }: { status: EvalRunStatus; progress: number }) {
  const styles: Record<EvalRunStatus, string> = {
    pending: "bg-navy-100 text-navy-700 dark:bg-navy-800 dark:text-navy-200",
    running: "bg-saffron-100 text-saffron-700 dark:bg-saffron-500/15 dark:text-saffron-300",
    completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  };
  const Icon = status === "completed" ? CheckCircle2 : status === "failed" ? CircleAlert : status === "running" ? Loader2 : Clock;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${styles[status]}`}>
      <Icon className={`size-3 ${status === "running" ? "animate-spin" : ""}`} aria-hidden />
      {status}
      {status === "running" && ` ${progress}%`}
    </span>
  );
}

// ---------------------------------------------------------------- dataset + run form
function DatasetCard({ dataset }: { dataset: DatasetStatus | null }) {
  if (!dataset) return <SkeletonLines lines={4} />;
  const ok = dataset.exists && dataset.errors.length === 0 && dataset.questions > 0;
  return (
    <div className="space-y-3 text-sm">
      <p className="break-all font-mono text-xs text-navy-500 dark:text-navy-400">{dataset.path}</p>
      {ok ? (
        <>
          <p>
            <span className="font-serif text-3xl font-bold">{dataset.questions}</span>{" "}
            <span className="text-navy-600 dark:text-navy-300">questions</span>
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {(Object.keys(CATEGORY_LABELS) as EvalCategory[]).map((c) => (
              <li key={c} className="rounded-md bg-navy-100 px-2 py-0.5 text-xs dark:bg-navy-800">
                {CATEGORY_LABELS[c]}: <strong>{dataset.by_category[c] ?? 0}</strong>
              </li>
            ))}
          </ul>
          {!dataset.by_category.out_of_scope && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Add some out_of_scope questions: the refusal accuracy and threshold report need them.
            </p>
          )}
        </>
      ) : !dataset.exists ? (
        <div className="rounded-lg bg-amber-50 p-3 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
          <p className="font-medium">No golden dataset yet.</p>
          <p className="mt-1">
            Copy <code className="font-mono">data/eval/golden.example.jsonl</code> to{" "}
            <code className="font-mono">golden.jsonl</code> and replace the examples with real questions written from the
            acts.
          </p>
        </div>
      ) : (
        <div className="rounded-lg bg-red-50 p-3 text-red-800 dark:bg-red-950 dark:text-red-200">
          <p className="font-medium">The dataset has problems:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
            {dataset.errors.slice(0, 8).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RunForm({ dataset, onStarted }: { dataset: DatasetStatus | null; onStarted: (id: string) => void }) {
  const toast = useToast();
  const [modes, setModes] = useState<RetrievalMode[]>(ALL_MODES);
  const [limit, setLimit] = useState("");
  const [generation, setGeneration] = useState(true);
  const [busy, setBusy] = useState(false);
  const ready = !!dataset && dataset.exists && dataset.errors.length === 0 && dataset.questions > 0;
  const questions = Math.min(dataset?.questions ?? 0, limit ? Number(limit) : Infinity);
  const llmCalls = generation ? questions * modes.length * 6 : 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { eval_run_id } = await api.evaluation.run({ modes, limit: limit ? Number(limit) : null, generation });
      toast.success("Evaluation started. It runs in the background.");
      onStarted(eval_run_id);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4 text-sm">
      <fieldset>
        <legend className="label">Modes to compare</legend>
        <div className="grid grid-cols-2 gap-1.5">
          {ALL_MODES.map((m) => (
            <label key={m} className="flex items-center gap-2 rounded-md px-1 py-0.5">
              <input
                type="checkbox"
                checked={modes.includes(m)}
                onChange={() => setModes((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]))}
                className="size-4 accent-saffron-500"
              />
              {MODE_LABELS[m]}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="limit" className="label">
            Question limit
          </label>
          <input id="limit" type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="All" className="input" />
        </div>
        <label className="flex items-end gap-2 pb-2">
          <input type="checkbox" checked={generation} onChange={(e) => setGeneration(e.target.checked)} className="size-4 accent-saffron-500" />
          Judge answers (LLM)
        </label>
      </div>
      <p className="text-xs text-navy-500 dark:text-navy-400">
        {generation
          ? `About ${llmCalls.toLocaleString()} LLM calls — mind free-tier rate limits. Untick to measure retrieval only.`
          : "Retrieval metrics only: no LLM calls."}
      </p>
      <button type="submit" disabled={!ready || busy || modes.length === 0} className="btn-primary w-full">
        {busy ? <Spinner /> : <Play className="size-4" aria-hidden />} Run evaluation
      </button>
    </form>
  );
}

// ---------------------------------------------------------------- results
type Column = { key: keyof ModeMetrics; label: string; format: (v: number | null | undefined) => string; better: "high" | "low"; generation?: boolean };

const COLUMNS: Column[] = [
  { key: "recall_at_5", label: "Recall@5", format: pct, better: "high" },
  { key: "recall_at_10", label: "Recall@10", format: pct, better: "high" },
  { key: "mrr", label: "MRR", format: (v) => num(v), better: "high" },
  { key: "faithfulness", label: "Faithfulness", format: pct, better: "high", generation: true },
  { key: "answer_relevance", label: "Relevance", format: pct, better: "high", generation: true },
  { key: "out_of_scope_refusal_accuracy", label: "OOS refused", format: pct, better: "high", generation: true },
  { key: "false_refusal_rate", label: "False refusals", format: pct, better: "low", generation: true },
  { key: "retrieval_latency_p50_ms", label: "Retrieval p50", format: ms, better: "low" },
  { key: "retrieval_latency_p95_ms", label: "Retrieval p95", format: ms, better: "low" },
  { key: "answer_latency_p95_ms", label: "Answer p95", format: ms, better: "low", generation: true },
  { key: "avg_tokens", label: "Avg tokens", format: (v) => (v == null ? "–" : Math.round(v).toLocaleString()), better: "low", generation: true },
];

function ComparisonTable({ modes, generation }: { modes: Partial<Record<RetrievalMode, ModeMetrics>>; generation: boolean }) {
  const rows = Object.entries(modes) as [RetrievalMode, ModeMetrics][];
  const columns = COLUMNS.filter((c) => generation || !c.generation);
  const best = (col: Column) => {
    const values = rows.map(([, m]) => m[col.key]).filter((v): v is number => typeof v === "number");
    if (values.length < 2) return null;
    return col.better === "high" ? Math.max(...values) : Math.min(...values);
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="text-xs uppercase tracking-wider text-navy-500 dark:text-navy-400">
          <tr className="border-b border-navy-100 dark:border-navy-800">
            <th scope="col" className="py-2 pr-3 text-left font-semibold">Mode</th>
            {columns.map((c) => (
              <th key={c.key} scope="col" className="px-2 py-2 text-right font-semibold whitespace-nowrap">
                {c.label}
              </th>
            ))}
            <th scope="col" className="py-2 pl-2 text-right font-semibold">Errors</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-navy-100 dark:divide-navy-800">
          {rows.map(([mode, m]) => (
            <tr key={mode}>
              <th scope="row" className="py-2.5 pr-3 text-left font-medium whitespace-nowrap">{MODE_LABELS[mode]}</th>
              {columns.map((c) => {
                const value = m[c.key];
                const isBest = typeof value === "number" && value === best(c);
                return (
                  <td key={c.key} className={`px-2 py-2.5 text-right tabular-nums ${isBest ? "font-bold text-saffron-600 dark:text-saffron-400" : ""}`}>
                    {c.format(typeof value === "number" ? value : null)}
                  </td>
                );
              })}
              <td className={`py-2.5 pl-2 text-right tabular-nums ${m.errors ? "text-red-600 dark:text-red-400" : "text-navy-400"}`}>{m.errors}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-navy-500 dark:text-navy-400">Best value per column highlighted. Retrieval metrics exclude out-of-scope questions.</p>
    </div>
  );
}

function ThresholdCard({ report }: { report: ThresholdReport }) {
  const changed = report.recommended !== null && Math.abs(report.recommended - report.current) >= 0.005;
  return (
    <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
      <div className="space-y-3 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wider text-navy-500 dark:text-navy-400">Recommended</p>
          <p className="font-serif text-4xl font-bold text-saffron-600 dark:text-saffron-400">{report.recommended ?? "–"}</p>
          <p className="text-xs text-navy-500 dark:text-navy-400">current: {report.current}</p>
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          <dt className="text-navy-500 dark:text-navy-400">Balanced accuracy</dt>
          <dd className="text-right font-medium tabular-nums">{pct(report.balanced_accuracy)}</dd>
          <dt className="text-navy-500 dark:text-navy-400">Answer recall</dt>
          <dd className="text-right font-medium tabular-nums">{pct(report.answer_recall)}</dd>
          <dt className="text-navy-500 dark:text-navy-400">Refusal recall</dt>
          <dd className="text-right font-medium tabular-nums">{pct(report.refusal_recall)}</dd>
          <dt className="text-navy-500 dark:text-navy-400">Questions</dt>
          <dd className="text-right tabular-nums">
            {report.answerable} answerable / {report.should_refuse} refuse
          </dd>
        </dl>
        {report.note && (
          <p className="flex gap-1.5 rounded-md bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden /> {report.note}
          </p>
        )}
        {changed && !report.note && (
          <p className="rounded-md bg-navy-50 p-2 text-xs dark:bg-navy-800">
            To apply it, set <code className="font-mono font-semibold">RERANK_REFUSAL_THRESHOLD={report.recommended}</code> in{" "}
            <code className="font-mono">.env</code> and restart the API.
          </p>
        )}
      </div>
      {report.curve.length > 0 && <ThresholdChart report={report} />}
    </div>
  );
}

function PerQuestion({ run }: { run: EvalRunDetail }) {
  const modes = Object.keys(run.metrics?.modes ?? {}) as RetrievalMode[];
  const [mode, setMode] = useState<RetrievalMode | undefined>(modes.includes("hybrid_rerank") ? "hybrid_rerank" : modes[0]);
  const rows = (run.per_question ?? []).filter((r) => r.mode === mode);
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-navy-700 dark:text-navy-200">
        <span className="transition-transform group-open:rotate-90">▸</span> Per-question results ({(run.per_question ?? []).length})
      </summary>
      <div className="mt-3">
        <label className="label" htmlFor="pq-mode">
          Mode
        </label>
        <select id="pq-mode" value={mode} onChange={(e) => setMode(e.target.value as RetrievalMode)} className="input mb-3 max-w-xs">
          {modes.map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m]}
            </option>
          ))}
        </select>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-xs uppercase tracking-wider text-navy-500 dark:text-navy-400">
              <tr className="border-b border-navy-100 dark:border-navy-800">
                {["ID", "Category", "R@5", "RR", "Best score", "Answer", "Faith.", "Relev.", "Top retrieved"].map((h) => (
                  <th key={h} scope="col" className="px-2 py-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-100 align-top dark:divide-navy-800">
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="px-2 py-2 font-mono text-xs">{r.id}</td>
                  <td className="px-2 py-2 text-xs">{CATEGORY_LABELS[r.category]}</td>
                  <td className="px-2 py-2 tabular-nums">{r.recall_at_5 == null ? "–" : pct(r.recall_at_5)}</td>
                  <td className="px-2 py-2 tabular-nums">{num(r.reciprocal_rank, 2)}</td>
                  <td className="px-2 py-2 tabular-nums">{num(r.best_rerank_score, 2)}</td>
                  <td className="px-2 py-2 text-xs">
                    {r.error ? (
                      <span className="text-red-600 dark:text-red-400">{r.error}</span>
                    ) : r.refused === undefined ? (
                      "–"
                    ) : r.refused ? (
                      <span className={r.category === "out_of_scope" ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-300"}>
                        refused ({r.refusal_reason})
                      </span>
                    ) : (
                      "answered"
                    )}
                  </td>
                  <td className="px-2 py-2 tabular-nums" title={r.faithfulness_note ?? undefined}>{num(r.faithfulness, 2)}</td>
                  <td className="px-2 py-2 tabular-nums" title={r.relevance_note ?? undefined}>{num(r.relevance, 2)}</td>
                  <td className="px-2 py-2 text-xs text-navy-500 dark:text-navy-400">{(r.retrieved ?? []).slice(0, 3).join(", ") || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}

function RunResults({ run }: { run: EvalRunDetail }) {
  if (run.status === "failed") {
    return (
      <p role="alert" className="flex gap-2 rounded-lg bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
        <CircleAlert className="size-4 shrink-0" aria-hidden /> {run.error ?? "The run failed."}
      </p>
    );
  }
  if (run.status !== "completed" || !run.metrics) {
    return (
      <div className="py-6">
        <div className="mx-auto max-w-md">
          <div className="h-2 overflow-hidden rounded-full bg-navy-100 dark:bg-navy-800" role="progressbar" aria-valuenow={run.progress} aria-valuemin={0} aria-valuemax={100} aria-label="Evaluation progress">
            <div className="h-full rounded-full bg-saffron-500 transition-all" style={{ width: `${Math.max(run.progress, 3)}%` }} />
          </div>
          <p className="mt-2 text-center text-sm text-navy-500 dark:text-navy-400">
            {run.status === "pending" ? "Waiting for the worker…" : `Evaluating… ${run.progress}%`}
          </p>
        </div>
      </div>
    );
  }
  const { modes, generation, threshold } = run.metrics;
  return (
    <div className="space-y-6">
      <ComparisonTable modes={modes} generation={generation} />
      <div className="grid gap-6 xl:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Retrieval quality</h3>
          <ModeBarChart
            modes={modes}
            percent
            series={[
              { key: "recall_at_5", label: "Recall@5" },
              { key: "recall_at_10", label: "Recall@10" },
              { key: "mrr", label: "MRR" },
            ]}
          />
        </div>
        {generation ? (
          <div>
            <h3 className="mb-2 text-sm font-semibold">Answer quality</h3>
            <ModeBarChart
              modes={modes}
              percent
              series={[
                { key: "faithfulness", label: "Faithfulness" },
                { key: "answer_relevance", label: "Relevance" },
                { key: "out_of_scope_refusal_accuracy", label: "OOS refused" },
              ]}
            />
          </div>
        ) : null}
        <div className={generation ? "xl:col-span-2" : ""}>
          <h3 className="mb-2 text-sm font-semibold">Latency</h3>
          <ModeBarChart
            modes={modes}
            unit=" ms"
            series={[
              { key: "retrieval_latency_p50_ms", label: "Retrieval p50" },
              { key: "retrieval_latency_p95_ms", label: "Retrieval p95" },
              ...(generation ? [{ key: "answer_latency_p95_ms" as const, label: "Answer p95" }] : []),
            ]}
          />
        </div>
      </div>
      {threshold && (
        <div className="border-t border-navy-100 pt-5 dark:border-navy-800">
          <h3 className="mb-3 flex items-center gap-2 font-serif text-lg font-semibold">
            <Target className="size-5 text-saffron-500" aria-hidden /> Re-ranker refusal threshold
          </h3>
          <ThresholdCard report={threshold} />
        </div>
      )}
      <PerQuestion run={run} />
    </div>
  );
}

// ---------------------------------------------------------------- page
export function EvaluationPage() {
  const toast = useToast();
  const [dataset, setDataset] = useState<DatasetStatus | null>(null);
  const [runs, setRuns] = useState<EvalRunSummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);

  const loadList = useCallback(async () => {
    try {
      const [ds, list] = await Promise.all([api.evaluation.dataset(), api.evaluation.runs()]);
      setDataset(ds);
      setRuns(list);
      setSelectedId((cur) => cur ?? list[0]?.id ?? null);
    } catch (err) {
      toast.error(describeError(err));
      setRuns((cur) => cur ?? []);
    }
  }, [toast]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  // Load the selected run, polling while it is still in progress.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const run = await api.evaluation.get(selectedId, controller.signal);
        setDetail(run);
        if (run.status === "pending" || run.status === "running") {
          timer = window.setTimeout(load, POLL_MS);
        } else {
          setRuns((list) => list?.map((r) => (r.id === run.id ? { ...r, ...run } : r)) ?? list);
        }
      } catch (err) {
        if (!controller.signal.aborted) toast.error(describeError(err));
      }
    };
    void load();
    return () => {
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [selectedId, toast]);

  const started = (id: string) => {
    setSelectedId(id);
    void loadList();
  };

  const selectedSummary = useMemo(() => runs?.find((r) => r.id === selectedId), [runs, selectedId]);

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
        <header>
          <h1 className="flex items-center gap-2 font-serif text-3xl font-bold">Evaluation</h1>
          <p className="mt-1 text-navy-600 dark:text-navy-300">
            Compare retrieval modes on your golden questions: recall, MRR, answer faithfulness and relevance, refusals and
            latency.
          </p>
        </header>

        <div className="grid gap-6 lg:grid-cols-[1fr_1fr_1.2fr]">
          <Section title="Golden dataset" icon={<Database className="size-5" aria-hidden />}>
            <DatasetCard dataset={dataset} />
          </Section>
          <Section title="New run" icon={<FlaskConical className="size-5" aria-hidden />}>
            <RunForm dataset={dataset} onStarted={started} />
          </Section>
          <Section title="History" icon={<History className="size-5" aria-hidden />}>
            {runs === null ? (
              <SkeletonLines lines={5} />
            ) : runs.length === 0 ? (
              <p className="text-sm text-navy-500 dark:text-navy-400">No runs yet.</p>
            ) : (
              <ul className="scroll-thin -mx-2 max-h-64 space-y-1 overflow-y-auto">
                {runs.map((r) => {
                  const head = r.headline.hybrid_rerank ?? Object.values(r.headline)[0];
                  return (
                    <li key={r.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(r.id)}
                        aria-current={r.id === selectedId}
                        className={`w-full rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                          r.id === selectedId ? "bg-saffron-50 dark:bg-saffron-500/10" : "hover:bg-navy-50 dark:hover:bg-navy-800"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{when(r.created_at)}</span>
                          <StatusBadge status={r.status} progress={r.progress} />
                        </div>
                        <p className="mt-0.5 text-xs text-navy-500 dark:text-navy-400">
                          {r.config.modes.length} modes{r.config.limit ? ` · ${r.config.limit} questions` : ""}
                          {r.config.generation ? " · judged" : " · retrieval only"}
                          {head && ` · R@5 ${pct(head.recall_at_5)} · MRR ${num(head.mrr, 2)}`}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
        </div>

        <Section
          title={selectedSummary ? `Run of ${when(selectedSummary.created_at)}` : "Results"}
          icon={<Gauge className="size-5" aria-hidden />}
        >
          {!selectedId ? (
            <EmptyState icon={<FlaskConical className="size-5" aria-hidden />} title="No evaluation yet">
              Once your golden dataset is in place, start a run to compare the four retrieval modes.
            </EmptyState>
          ) : !detail || detail.id !== selectedId ? (
            <SkeletonLines lines={6} />
          ) : (
            <RunResults run={detail} />
          )}
        </Section>
      </div>
    </div>
  );
}
