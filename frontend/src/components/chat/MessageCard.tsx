import {
  AlertTriangle,
  Check,
  Copy,
  Info,
  Loader2,
  ThumbsDown,
  ThumbsUp,
  Zap,
} from "lucide-react";
import { useState } from "react";

import { api, describeError } from "../../api/client";
import type { ChatMessage } from "../../hooks/useChat";
import type { PipelineStage } from "../../types/api";
import { useToast } from "../Toasts";
import { ActBadge } from "../ui";
import { AnswerText } from "./AnswerText";

const STAGES: { stage: PipelineStage; label: string }[] = [
  { stage: "checking", label: "Checking query" },
  { stage: "searching", label: "Searching 2 indexes" },
  { stage: "reranking", label: "Re-ranking" },
  { stage: "generating", label: "Writing answer" },
  { stage: "verifying", label: "Verifying citations" },
];

const MODE_LABELS: Record<string, string> = {
  vector: "Vector",
  keyword: "Keyword",
  hybrid: "Hybrid",
  hybrid_rerank: "Hybrid + re-rank",
};

function StatusChips({ message }: { message: ChatMessage }) {
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Pipeline progress">
      {STAGES.map(({ stage, label }) => {
        const done = message.completedStages.includes(stage);
        const active = message.stage === stage;
        if (!done && !active) return null;
        return (
          <li
            key={stage}
            className={`flex animate-fade-in items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
              active
                ? "border-saffron-300 bg-saffron-50 text-saffron-700 dark:border-saffron-500/40 dark:bg-saffron-500/10 dark:text-saffron-300"
                : "border-navy-100 bg-navy-50 text-navy-500 dark:border-navy-700 dark:bg-navy-800 dark:text-navy-300"
            }`}
          >
            {active ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Check className="size-3" aria-hidden />}
            {label}
            {active && "…"}
          </li>
        );
      })}
    </ol>
  );
}

function FeedbackButtons({ message, onRated }: { message: ChatMessage; onRated: (r: 1 | -1) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const logId = message.response?.query_log_id;
  if (!logId) return null;

  const rate = async (rating: 1 | -1) => {
    setBusy(true);
    try {
      await api.query.feedback(logId, rating);
      onRated(rating);
      toast.success(rating === 1 ? "Thanks — marked as helpful." : "Thanks — we'll use this to improve.");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const button = (rating: 1 | -1, Icon: typeof ThumbsUp, label: string) => {
    const selected = message.feedback === rating;
    return (
      <button
        type="button"
        onClick={() => rate(rating)}
        disabled={busy}
        aria-pressed={selected}
        aria-label={label}
        title={label}
        className={`rounded-md p-1.5 transition-colors ${
          selected
            ? "bg-saffron-100 text-saffron-700 dark:bg-saffron-500/20 dark:text-saffron-300"
            : "text-navy-400 hover:bg-navy-100 hover:text-navy-700 dark:hover:bg-navy-800 dark:hover:text-navy-100"
        }`}
      >
        <Icon className="size-4" aria-hidden />
      </button>
    );
  };

  return (
    <div className="flex items-center gap-0.5">
      {button(1, ThumbsUp, "Helpful")}
      {button(-1, ThumbsDown, "Not helpful")}
    </div>
  );
}

function CopyButton({ message }: { message: ChatMessage }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const response = message.response;
  if (!response) return null;

  const copy = async () => {
    const sources = response.citations
      .map((c) => `[${c.n}] ${c.act} s. ${c.section_number}${c.section_title ? ` – ${c.section_title}` : ""}`)
      .join("\n");
    const text = `${response.answer}\n\n${sources ? `Sources:\n${sources}\n\n` : ""}${response.disclaimer}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy to the clipboard.");
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-navy-500 hover:bg-navy-100 hover:text-navy-800 dark:text-navy-400 dark:hover:bg-navy-800 dark:hover:text-navy-100"
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

interface Props {
  message: ChatMessage;
  selected: boolean;
  activeCitation: number | null;
  onSelect: () => void;
  onCite: (n: number) => void;
  onRated: (rating: 1 | -1) => void;
}

export function MessageCard({ message, selected, activeCitation, onSelect, onCite, onRated }: Props) {
  const response = message.response;
  const text = response?.answer ?? message.draft;
  const refused = response?.refused ?? false;

  return (
    <article className="animate-fade-in space-y-3" aria-busy={message.status === "streaming"}>
      {/* the question */}
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-navy-800 px-4 py-2.5 text-sm text-white shadow-sm dark:bg-navy-700">
          <p className="whitespace-pre-wrap">{message.question}</p>
          {(message.acts.length > 0 || message.mode !== "hybrid_rerank") && (
            <p className="mt-1.5 flex flex-wrap items-center gap-1 text-[0.7rem] text-navy-200">
              {message.acts.map((a) => (
                <span key={a} className="rounded bg-white/10 px-1.5 py-0.5 font-semibold">
                  {a}
                </span>
              ))}
              {message.mode !== "hybrid_rerank" && <span className="opacity-80">· {MODE_LABELS[message.mode]}</span>}
            </p>
          )}
        </div>
      </div>

      {/* the answer */}
      <div
        onClick={onSelect}
        className={`card cursor-default p-4 transition-shadow sm:p-5 ${
          selected && message.citations.length ? "ring-2 ring-saffron-400/60 dark:ring-saffron-500/40" : ""
        }`}
      >
        {message.status === "streaming" && <StatusChips message={message} />}

        {message.status === "streaming" && !text && (
          <div className="mt-4 space-y-2" aria-hidden>
            <div className="skeleton h-3.5 w-11/12" />
            <div className="skeleton h-3.5 w-9/12" />
          </div>
        )}

        {message.status === "error" && (
          <div role="alert" className="flex items-start gap-2.5 rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/60 dark:text-red-200">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div>
              <p className="font-medium">No answer this time.</p>
              <p className="mt-0.5">{message.error}</p>
            </div>
          </div>
        )}

        {text && message.status !== "error" && (
          <div className={message.status === "streaming" ? "mt-3" : ""}>
            {refused ? (
              <div className="flex items-start gap-2.5 rounded-lg bg-navy-50 p-3 text-sm text-navy-700 dark:bg-navy-800 dark:text-navy-200">
                <Info className="mt-0.5 size-4 shrink-0 text-saffron-500" aria-hidden />
                <p>{text}</p>
              </div>
            ) : (
              <AnswerText
                text={text}
                citations={message.citations}
                activeCitation={selected ? activeCitation : null}
                onCite={(n) => {
                  onSelect();
                  onCite(n);
                }}
                streaming={message.status === "streaming"}
              />
            )}
          </div>
        )}

        {response && response.warnings.length > 0 && (
          <div
            role="note"
            className="mt-4 space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-600/50 dark:bg-amber-500/10 dark:text-amber-200"
          >
            {response.warnings.map((w) => (
              <p key={w} className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {w}
              </p>
            ))}
          </div>
        )}

        {response && (
          <footer className="mt-4 space-y-3 border-t border-navy-100 pt-3 dark:border-navy-800">
            {!refused && response.citations.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {response.citations.map((c) => (
                  <button
                    key={c.n}
                    type="button"
                    onClick={() => {
                      onSelect();
                      onCite(c.n);
                    }}
                    className="flex items-center gap-1 rounded-md border border-navy-100 px-2 py-0.5 text-xs hover:border-saffron-300 hover:bg-saffron-50 dark:border-navy-700 dark:hover:border-saffron-500/50 dark:hover:bg-saffron-500/10"
                  >
                    <span className="font-bold text-navy-500 dark:text-navy-300">{c.n}</span>
                    <ActBadge code={c.act} status={c.act_status} />
                    <span>§ {c.section_number}</span>
                  </button>
                ))}
              </div>
            )}
            <p className="text-xs leading-relaxed text-navy-500 dark:text-navy-400">{response.disclaimer}</p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <FeedbackButtons message={message} onRated={onRated} />
                <CopyButton message={message} />
              </div>
              <p className="flex items-center gap-1 text-xs text-navy-400">
                {response.cache_hit && (
                  <span className="flex items-center gap-0.5 text-saffron-600 dark:text-saffron-400" title="Served from cache">
                    <Zap className="size-3" aria-hidden /> cached ·
                  </span>
                )}
                {(response.latency_ms / 1000).toFixed(1)} s
              </p>
            </div>
          </footer>
        )}
      </div>
    </article>
  );
}
