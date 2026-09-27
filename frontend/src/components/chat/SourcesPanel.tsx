import { FileSearch, PanelRightOpen } from "lucide-react";
import { useEffect, useRef } from "react";

import type { Citation } from "../../types/api";
import { ActBadge, RepealedTag } from "../ui";

interface Props {
  citations: Citation[];
  activeCitation: number | null;
  onOpen: (citation: Citation) => void;
}

export function SourcesPanel({ citations, activeCitation, onOpen }: Props) {
  const refs = useRef(new Map<number, HTMLLIElement>());

  useEffect(() => {
    if (activeCitation !== null) {
      refs.current.get(activeCitation)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [activeCitation]);

  return (
    <section aria-labelledby="sources-heading" className="flex h-full flex-col">
      <div className="flex items-center justify-between px-4 py-3">
        <h2 id="sources-heading" className="font-serif text-lg font-semibold">
          Sources
        </h2>
        {citations.length > 0 && <span className="text-xs text-navy-500 dark:text-navy-400">{citations.length} cited</span>}
      </div>

      {citations.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 pb-12 text-center text-sm text-navy-500 dark:text-navy-400">
          <FileSearch className="size-8 text-navy-300 dark:text-navy-600" aria-hidden />
          <p>Cited sections appear here. Click a card to read the full section.</p>
        </div>
      ) : (
        <ol className="scroll-thin flex-1 space-y-2.5 overflow-y-auto px-4 pb-4">
          {citations.map((c) => {
            const active = c.n === activeCitation;
            return (
              <li
                key={c.n}
                ref={(el) => {
                  if (el) refs.current.set(c.n, el);
                  else refs.current.delete(c.n);
                }}
              >
                <button
                  type="button"
                  onClick={() => onOpen(c)}
                  className={`group w-full rounded-xl border p-3.5 text-left transition-all ${
                    active
                      ? "border-saffron-400 bg-saffron-50 shadow-sm dark:border-saffron-500/60 dark:bg-saffron-500/10"
                      : "border-navy-100 bg-white hover:border-navy-200 hover:shadow-sm dark:border-navy-800 dark:bg-navy-900 dark:hover:border-navy-700"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`grid size-5 place-items-center rounded text-[0.7rem] font-bold ${
                        active ? "bg-saffron-500 text-navy-950" : "bg-navy-100 text-navy-700 dark:bg-navy-700 dark:text-navy-100"
                      }`}
                    >
                      {c.n}
                    </span>
                    <ActBadge code={c.act} status={c.act_status} />
                    {c.act_status === "repealed" && <RepealedTag />}
                    {c.page_start && <span className="ml-auto text-xs text-navy-400">p. {c.page_start}</span>}
                  </div>
                  <p className="mt-2 font-serif font-semibold leading-snug">
                    Section {c.section_number}
                    {c.section_title && <span className="font-normal">: {c.section_title}</span>}
                  </p>
                  <p className="mt-1.5 line-clamp-4 font-serif text-sm leading-relaxed text-navy-600 dark:text-navy-300">
                    {c.snippet}
                  </p>
                  <span className="mt-2 flex items-center gap-1 text-xs font-medium text-saffron-600 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 dark:text-saffron-400">
                    <PanelRightOpen className="size-3.5" aria-hidden /> Read full section
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
