import { ArrowRight, ArrowRightLeft, FileQuestion, Search } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { api, ApiError, describeError } from "../api/client";
import { SectionText } from "../components/chat/SectionDrawer";
import { ActBadge, EmptyState, RepealedTag, SkeletonLines, Spinner } from "../components/ui";
import type { MappingView, SectionView } from "../types/api";

type Load =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "not-found"; message: string }
  | { kind: "error"; message: string }
  | { kind: "ok"; data: MappingView };

function SectionColumn({
  act,
  section,
  view,
  note,
}: {
  act: string;
  section: string;
  view: SectionView | null;
  note?: string | null;
}) {
  return (
    <div className="card flex flex-col overflow-hidden">
      <div className="border-b border-navy-100 px-5 py-4 dark:border-navy-800">
        <div className="flex items-center gap-2">
          <ActBadge code={act} status={view?.act_status} />
          {view?.act_status === "repealed" && <RepealedTag />}
        </div>
        <h2 className="mt-1.5 font-serif text-xl font-bold">
          Section {section}
          {view?.section_title && <span className="font-normal">: {view.section_title}</span>}
        </h2>
        {view && (
          <p className="mt-0.5 text-xs text-navy-500 dark:text-navy-400">
            {view.act_name}
            {view.page_start && ` · p. ${view.page_start}`}
          </p>
        )}
        {note && (
          <p className="mt-2 rounded-md bg-saffron-50 px-2.5 py-1.5 text-xs text-saffron-700 dark:bg-saffron-500/10 dark:text-saffron-300">
            {note}
          </p>
        )}
      </div>
      <div className="scroll-thin max-h-[60vh] overflow-y-auto px-5 py-4">
        {view ? (
          <SectionText text={view.text} />
        ) : (
          <p className="text-sm text-navy-500 dark:text-navy-400">
            The text of {act} section {section} isn't available because that act hasn't been uploaded yet.
          </p>
        )}
      </div>
    </div>
  );
}

export function MapperPage() {
  const [input, setInput] = useState("");
  const [load, setLoad] = useState<Load>({ kind: "idle" });
  const controller = useRef<AbortController | null>(null);

  const lookup = async (raw: string) => {
    const section = raw.trim().replace(/^(ipc|section|sec\.?|s\.?)\s*/i, "");
    if (!section) return;
    setInput(section);
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setLoad({ kind: "loading" });
    try {
      setLoad({ kind: "ok", data: await api.catalog.ipcMapping(section, abort.signal) });
    } catch (err) {
      if (abort.signal.aborted) return;
      if (err instanceof ApiError && (err.status === 404 || err.status === 400)) {
        setLoad({ kind: "not-found", message: err.message });
      } else {
        setLoad({ kind: "error", message: describeError(err) });
      }
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void lookup(input);
  };

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <header className="max-w-2xl">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-saffron-600 dark:text-saffron-400">
            <ArrowRightLeft className="size-3.5" aria-hidden /> IPC → BNS mapper
          </p>
          <h1 className="mt-2 font-serif text-3xl font-bold">Find the new section for an old one</h1>
          <p className="mt-2 text-navy-600 dark:text-navy-300">
            Enter an Indian Penal Code section to see the Bharatiya Nyaya Sanhita provision that replaced it, side by
            side. Mappings come from the verified table loaded by your administrator.
          </p>
        </header>

        <form onSubmit={onSubmit} className="mt-6 flex max-w-xl gap-2" role="search">
          <label htmlFor="ipc-section" className="sr-only">
            IPC section number
          </label>
          <div className="relative flex-1">
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm font-semibold text-navy-400">
              IPC
            </span>
            <input
              id="ipc-section"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. 420 or 498A"
              className="input py-2.5 pl-12"
              autoComplete="off"
              inputMode="text"
            />
          </div>
          <button type="submit" disabled={!input.trim() || load.kind === "loading"} className="btn-primary px-5">
            {load.kind === "loading" ? <Spinner /> : <Search className="size-4" aria-hidden />} Look up
          </button>
        </form>

        <div className="mt-8" aria-live="polite">
          {load.kind === "idle" && (
            <EmptyState icon={<ArrowRightLeft className="size-5" aria-hidden />} title="Look up an IPC section">
              The old and new text appear side by side so you can compare wording and punishment.
            </EmptyState>
          )}
          {load.kind === "loading" && (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card p-5">
                <SkeletonLines lines={8} />
              </div>
              <div className="card p-5">
                <SkeletonLines lines={8} />
              </div>
            </div>
          )}
          {load.kind === "not-found" && (
            <EmptyState icon={<FileQuestion className="size-5" aria-hidden />} title="No mapping found">
              {load.message}
            </EmptyState>
          )}
          {load.kind === "error" && (
            <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
              {load.message}
            </p>
          )}
          {load.kind === "ok" && (
            <div className="space-y-4">
              {load.data.targets.length === 0 && (
                <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
                  IPC section {load.data.from_section} is indexed, but the mapping table has no BNS equivalent for it.
                </p>
              )}
              {(load.data.targets.length ? load.data.targets : [null]).map((target, i) => (
                <div key={i} className="grid items-start gap-4 lg:grid-cols-[1fr_auto_1fr]">
                  <SectionColumn act="IPC" section={load.data.from_section} view={load.data.source} />
                  <div className="hidden self-center lg:block">
                    <span className="grid size-10 place-items-center rounded-full bg-saffron-500 text-navy-950 shadow">
                      <ArrowRight className="size-5" aria-hidden />
                    </span>
                  </div>
                  {target && (
                    <SectionColumn
                      act={target.to_act}
                      section={target.to_section}
                      view={target.section}
                      note={target.note}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
