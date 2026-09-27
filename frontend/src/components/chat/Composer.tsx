import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

const MAX_CHARS = 1000;

interface Props {
  busy: boolean;
  onSend: (question: string) => void;
  onStop: () => void;
  prefill: string | null;
}

export function Composer({ busy, onSend, onStop, prefill }: Props) {
  const [value, setValue] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (prefill !== null) {
      setValue(prefill);
      textarea.current?.focus();
    }
  }, [prefill]);

  // Auto-grow up to ~8 lines.
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const trimmed = value.trim();
  const tooLong = value.length > MAX_CHARS;
  const canSend = !busy && trimmed.length >= 3 && !tooLong;

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend) return;
    onSend(trimmed);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl">
      <div className="card flex items-end gap-2 p-2 focus-within:border-saffron-400 focus-within:ring-2 focus-within:ring-saffron-500/20">
        <label htmlFor="question" className="sr-only">
          Ask a question about Indian law
        </label>
        <textarea
          id="question"
          ref={textarea}
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about BNS, BNSS, BSA, the IT Act or the IPC…"
          className="max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[0.95rem] placeholder:text-navy-400 focus:outline-none"
          aria-describedby="composer-hint"
        />
        {busy ? (
          <button type="button" onClick={onStop} className="btn-ghost size-10 shrink-0 p-0" aria-label="Stop generating" title="Stop">
            <Square className="size-4 fill-current" aria-hidden />
          </button>
        ) : (
          <button type="submit" disabled={!canSend} className="btn-accent size-10 shrink-0 rounded-lg p-0" aria-label="Send question">
            <ArrowUp className="size-5" aria-hidden />
          </button>
        )}
      </div>
      <p id="composer-hint" className="mt-1.5 flex justify-between px-1 text-xs text-navy-400">
        <span>Enter to send · Shift + Enter for a new line</span>
        <span className={tooLong ? "font-medium text-red-600" : undefined}>
          {value.length > MAX_CHARS * 0.8 && `${value.length}/${MAX_CHARS}`}
        </span>
      </p>
    </form>
  );
}
