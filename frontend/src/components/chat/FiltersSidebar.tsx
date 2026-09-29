import { History, Library, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, describeError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import type { ActSummary, RetrievalMode } from "../../types/api";
import { RepealedTag } from "../ui";

export const MODES: { value: RetrievalMode; label: string; hint: string }[] = [
  { value: "hybrid_rerank", label: "Hybrid + re-rank", hint: "Best quality (default)" },
  { value: "hybrid", label: "Hybrid (RRF)", hint: "Keyword + vector, fused" },
  { value: "vector", label: "Vector only", hint: "Semantic similarity" },
  { value: "keyword", label: "Keyword only", hint: "Full-text search" },
];

type ActsLoad = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ok"; acts: ActSummary[] };

interface Props {
  selectedActs: string[];
  onActsChange: (acts: string[]) => void;
  mode: RetrievalMode;
  onModeChange: (mode: RetrievalMode) => void;
  recent: string[];
  onRecent: (question: string) => void;
  onClearRecent: () => void;
  disabled: boolean;
}

export function FiltersSidebar(props: Props) {
  const { user } = useAuth();
  const [load, setLoad] = useState<ActsLoad>({ kind: "loading" });

  useEffect(() => {
    api.catalog
      .acts()
      // An act left without an ingested document has nothing to search; don't offer it.
      .then((acts) => setLoad({ kind: "ok", acts: acts.filter((a) => a.chunks_count > 0) }))
      .catch((err: unknown) => setLoad({ kind: "error", message: describeError(err) }));
  }, []);

  const toggle = (code: string) =>
    props.onActsChange(
      props.selectedActs.includes(code)
        ? props.selectedActs.filter((a) => a !== code)
        : [...props.selectedActs, code],
    );

  return (
    <div className="scroll-thin flex h-full flex-col gap-6 overflow-y-auto p-4">
      <fieldset>
        <legend className="mb-2 flex w-full items-center gap-2 text-xs font-semibold uppercase tracking-wider text-navy-500 dark:text-navy-400">
          <Library className="size-3.5" aria-hidden /> Acts
          {props.selectedActs.length > 0 && (
            <button
              type="button"
              onClick={() => props.onActsChange([])}
              className="ml-auto text-[0.7rem] font-medium normal-case tracking-normal text-saffron-600 hover:underline dark:text-saffron-400"
            >
              Clear
            </button>
          )}
        </legend>
        {load.kind === "loading" && (
          <div className="space-y-2.5" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-6" />
            ))}
          </div>
        )}
        {load.kind === "error" && <p className="text-sm text-red-600 dark:text-red-400">{load.message}</p>}
        {load.kind === "ok" && load.acts.length === 0 && (
          <p className="rounded-lg bg-navy-100/60 p-3 text-sm text-navy-600 dark:bg-navy-800 dark:text-navy-300">
            No acts are indexed yet.
            {user?.role === "admin" && (
              <>
                {" "}
                <Link to="/admin/documents" className="font-medium text-saffron-600 hover:underline dark:text-saffron-400">
                  Upload a bare act
                </Link>
                .
              </>
            )}
          </p>
        )}
        {load.kind === "ok" && load.acts.length > 0 && (
          <>
            <ul className="space-y-0.5">
              {load.acts.map((act) => (
                <li key={act.short_code}>
                  <label
                    className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2 py-1.5 hover:bg-navy-100/70 dark:hover:bg-navy-800"
                    title={act.full_name}
                  >
                    <input
                      type="checkbox"
                      checked={props.selectedActs.includes(act.short_code)}
                      onChange={() => toggle(act.short_code)}
                      disabled={props.disabled}
                      className="mt-0.5 size-4 rounded accent-saffron-500"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        {act.short_code}
                        {act.status === "repealed" && <RepealedTag />}
                      </span>
                      <span className="block truncate text-xs text-navy-500 dark:text-navy-400">
                        {act.full_name}, {act.year}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <p className="mt-2 px-2 text-xs text-navy-500 dark:text-navy-400">
              {props.selectedActs.length === 0
                ? "Searching all acts in force. Tick IPC to include the repealed code."
                : `Searching ${props.selectedActs.join(", ")} only.`}
            </p>
          </>
        )}
      </fieldset>

      <div>
        <label
          htmlFor="mode"
          className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-navy-500 dark:text-navy-400"
        >
          <SlidersHorizontal className="size-3.5" aria-hidden /> Retrieval mode
        </label>
        <select
          id="mode"
          value={props.mode}
          onChange={(e) => props.onModeChange(e.target.value as RetrievalMode)}
          disabled={props.disabled}
          className="input"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
        <p className="mt-1.5 text-xs text-navy-500 dark:text-navy-400">
          {MODES.find((m) => m.value === props.mode)?.hint}
        </p>
      </div>

      <div className="min-h-0">
        <h2 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-navy-500 dark:text-navy-400">
          <History className="size-3.5" aria-hidden /> Recent questions
          {props.recent.length > 0 && (
            <button
              type="button"
              onClick={props.onClearRecent}
              className="ml-auto rounded p-0.5 hover:text-red-600"
              aria-label="Clear recent questions"
              title="Clear"
            >
              <Trash2 className="size-3.5" aria-hidden />
            </button>
          )}
        </h2>
        {props.recent.length === 0 ? (
          <p className="px-2 text-sm text-navy-400">Your questions will appear here.</p>
        ) : (
          <ul className="space-y-0.5">
            {props.recent.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => props.onRecent(q)}
                  disabled={props.disabled}
                  className="w-full truncate rounded-lg px-2 py-1.5 text-left text-sm text-navy-700 hover:bg-navy-100/70 disabled:opacity-50 dark:text-navy-200 dark:hover:bg-navy-800"
                  title={q}
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
