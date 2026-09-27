import { BookMarked, Filter, RotateCcw, Scale, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Composer } from "../components/chat/Composer";
import { FiltersSidebar } from "../components/chat/FiltersSidebar";
import { MessageCard } from "../components/chat/MessageCard";
import { SectionDrawer, type SectionRef } from "../components/chat/SectionDrawer";
import { SourcesPanel } from "../components/chat/SourcesPanel";
import { Drawer } from "../components/ui";
import { useChat } from "../hooks/useChat";
import type { Citation, RetrievalMode } from "../types/api";

const EXAMPLES = [
  "What is the punishment for cheating under BNS?",
  "Which BNS section replaced IPC 420?",
  "What does Section 66C of the IT Act say?",
  "Can the police arrest without a warrant?",
];

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

function Welcome({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-10 text-center sm:py-16">
      <div className="grid size-14 place-items-center rounded-2xl bg-navy-800 text-saffron-400 shadow-lg dark:bg-navy-800">
        <Scale className="size-7" aria-hidden />
      </div>
      <h1 className="mt-6 font-serif text-3xl font-bold sm:text-4xl">What does the law say?</h1>
      <p className="mt-3 max-w-lg text-navy-600 dark:text-navy-300">
        Ask in plain English or Hinglish. Answers come only from the bare acts, with the exact section behind
        every sentence.
      </p>
      <div className="mt-8 grid w-full gap-2.5 sm:grid-cols-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="card px-4 py-3 text-left text-sm transition-all hover:-translate-y-0.5 hover:border-saffron-300 hover:shadow-md dark:hover:border-saffron-500/50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ChatPage() {
  const chat = useChat();
  const [acts, setActs] = useState<string[]>([]);
  const [mode, setMode] = useState<RetrievalMode>("hybrid_rerank");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<number | null>(null);
  const [section, setSection] = useState<SectionRef | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [prefill, setPrefill] = useState<string | null>(null);
  const wide = useMediaQuery("(min-width: 1280px)");
  const thread = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const latest = chat.messages[chat.messages.length - 1];
  const selected = chat.messages.find((m) => m.id === selectedId) ?? latest;
  const citations = useMemo(() => selected?.citations ?? [], [selected]);

  // Follow the newest message.
  useEffect(() => {
    if (latest) {
      setSelectedId(latest.id);
      setActiveCitation(null);
    }
  }, [latest?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep scrolled to the bottom while streaming, unless the user scrolled up.
  useEffect(() => {
    const el = thread.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [chat.messages]);

  const onScroll = () => {
    const el = thread.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const send = useCallback(
    (question: string) => {
      stickToBottom.current = true;
      setFiltersOpen(false);
      void chat.ask(question, acts, mode);
    },
    [chat, acts, mode],
  );

  const onCite = (n: number) => {
    setActiveCitation(n);
    if (!wide) setSourcesOpen(true);
  };

  const openSection = (c: Citation) => setSection({ act: c.act, section: c.section_number });

  const sidebar = (
    <FiltersSidebar
      selectedActs={acts}
      onActsChange={setActs}
      mode={mode}
      onModeChange={setMode}
      recent={chat.recent}
      onRecent={(q) => {
        setFiltersOpen(false);
        setPrefill(q);
      }}
      onClearRecent={chat.clearRecent}
      disabled={chat.busy}
    />
  );

  const sources = <SourcesPanel citations={citations} activeCitation={activeCitation} onOpen={openSection} />;

  return (
    <div className="flex h-full">
      <aside
        aria-label="Search filters"
        className="hidden w-72 shrink-0 border-r border-navy-100 bg-white/60 lg:block dark:border-navy-800 dark:bg-navy-900/40"
      >
        {sidebar}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        {/* toolbar */}
        <div className="flex items-center gap-2 border-b border-navy-100 px-3 py-2 dark:border-navy-800 lg:hidden">
          <button type="button" onClick={() => setFiltersOpen(true)} className="btn-ghost px-2.5 py-1.5">
            <Filter className="size-4" aria-hidden /> Filters
            {acts.length > 0 && (
              <span className="rounded-full bg-saffron-500 px-1.5 text-xs font-bold text-navy-950">{acts.length}</span>
            )}
          </button>
          {!wide && citations.length > 0 && (
            <button type="button" onClick={() => setSourcesOpen(true)} className="btn-ghost ml-auto px-2.5 py-1.5">
              <BookMarked className="size-4" aria-hidden /> Sources ({citations.length})
            </button>
          )}
        </div>

        <div ref={thread} onScroll={onScroll} className="scroll-thin flex-1 overflow-y-auto" aria-live="polite">
          {chat.messages.length === 0 ? (
            <Welcome onPick={send} />
          ) : (
            <div className="mx-auto max-w-3xl space-y-8 px-3 py-6 sm:px-6">
              {chat.messages.map((m) => (
                <MessageCard
                  key={m.id}
                  message={m}
                  selected={m.id === selected?.id}
                  activeCitation={activeCitation}
                  onSelect={() => {
                    if (m.id !== selectedId) {
                      setSelectedId(m.id);
                      setActiveCitation(null);
                    }
                  }}
                  onCite={onCite}
                  onRated={(rating) => chat.setFeedback(m.id, rating)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-navy-100 bg-navy-50/80 px-3 pb-3 pt-3 backdrop-blur dark:border-navy-800 dark:bg-navy-950/80 sm:px-6">
          {chat.messages.length > 0 && !chat.busy && (
            <div className="mx-auto mb-2 flex max-w-3xl justify-end">
              <button type="button" onClick={chat.reset} className="btn-ghost px-2 py-1 text-xs">
                <RotateCcw className="size-3.5" aria-hidden /> New conversation
              </button>
            </div>
          )}
          <Composer busy={chat.busy} onSend={send} onStop={chat.stop} prefill={prefill} />
        </div>
      </section>

      <aside
        aria-label="Sources"
        className="hidden w-[22rem] shrink-0 border-l border-navy-100 bg-white/60 xl:block dark:border-navy-800 dark:bg-navy-900/40"
      >
        {sources}
      </aside>

      {/* small screens: filters and sources as slide-overs */}
      {filtersOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Filters">
          <button type="button" aria-label="Close filters" className="absolute inset-0 bg-navy-950/40" onClick={() => setFiltersOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-80 max-w-[85%] animate-fade-in bg-white shadow-2xl dark:bg-navy-900">
            <div className="flex justify-end p-2">
              <button type="button" onClick={() => setFiltersOpen(false)} className="btn-ghost p-2" aria-label="Close">
                <X className="size-5" aria-hidden />
              </button>
            </div>
            {sidebar}
          </div>
        </div>
      )}
      <Drawer open={!wide && sourcesOpen} onClose={() => setSourcesOpen(false)} title={<span className="sr-only">Sources</span>}>
        <div className="-mx-5 -my-4">{sources}</div>
      </Drawer>

      <SectionDrawer target={section} onClose={() => setSection(null)} />
    </div>
  );
}
