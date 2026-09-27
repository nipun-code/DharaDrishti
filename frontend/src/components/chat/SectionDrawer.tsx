import { AlertCircle, BookOpen } from "lucide-react";
import { useEffect, useState } from "react";

import { api, describeError } from "../../api/client";
import type { SectionView } from "../../types/api";
import { ActBadge, Drawer, RepealedTag, SkeletonLines } from "../ui";

export interface SectionRef {
  act: string;
  section: string;
}

type Load = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ok"; data: SectionView };

export function SectionText({ text }: { text: string }) {
  return (
    <div className="legal-text space-y-2.5 text-navy-900 dark:text-navy-100">
      {text.split("\n").map((line, i) => (
        <p
          key={i}
          className={/^\s*\((?:\d+|[a-z]{1,3}|[ivx]+)\)/.test(line) ? "pl-4" : /^(Explanation|Illustration|Provided|Exception)/.test(line) ? "border-l-2 border-saffron-300 pl-3 text-navy-700 italic dark:border-saffron-500/50 dark:text-navy-300" : undefined}
        >
          {line}
        </p>
      ))}
    </div>
  );
}

/** Full section text, fetched when opened. */
export function SectionDrawer({ target, onClose }: { target: SectionRef | null; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });

  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    setLoad({ kind: "loading" });
    api.catalog
      .section(target.act, target.section, controller.signal)
      .then((data) => setLoad({ kind: "ok", data }))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: "error", message: describeError(err) });
      });
    return () => controller.abort();
  }, [target]);

  const data = load.kind === "ok" ? load.data : null;
  return (
    <Drawer
      open={target !== null}
      onClose={onClose}
      title={
        <div>
          <div className="flex items-center gap-2">
            {target && <ActBadge code={target.act} status={data?.act_status} />}
            {data?.act_status === "repealed" && <RepealedTag />}
          </div>
          <h2 className="mt-1.5 font-serif text-xl font-bold leading-snug">
            Section {target?.section}
            {data?.section_title && <span className="font-normal">: {data.section_title}</span>}
          </h2>
          {data && (
            <p className="mt-1 text-xs text-navy-500 dark:text-navy-400">
              {data.act_name}
              {data.chapter_number && ` · Chapter ${data.chapter_number}${data.chapter_title ? `: ${data.chapter_title}` : ""}`}
              {data.page_start && ` · p. ${data.page_start}${data.page_end && data.page_end !== data.page_start ? `–${data.page_end}` : ""}`}
            </p>
          )}
        </div>
      }
    >
      {load.kind === "loading" && <SkeletonLines lines={10} />}
      {load.kind === "error" && (
        <div className="flex items-start gap-3 rounded-lg bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {load.message}
        </div>
      )}
      {data && (
        <>
          <SectionText text={data.text} />
          <p className="mt-6 flex items-center gap-2 border-t border-navy-100 pt-4 text-xs text-navy-500 dark:border-navy-800 dark:text-navy-400">
            <BookOpen className="size-3.5" aria-hidden /> Text as extracted from the uploaded bare act PDF.
          </p>
        </>
      )}
    </Drawer>
  );
}
