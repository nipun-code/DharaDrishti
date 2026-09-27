/**
 * Renders an answer: paragraphs, simple bullet/numbered lists, **bold**, and [n] citation
 * markers as clickable badges. Deliberately tiny — no HTML is ever injected.
 */

import { Fragment, type ReactNode } from "react";

import type { Citation } from "../../types/api";

const INLINE_RE = /(\*\*[^*]+\*\*|\[\d{1,3}\])/g;
const LIST_ITEM_RE = /^\s*(?:[-*•]|\d{1,2}[.)])\s+/;

interface Props {
  text: string;
  citations: Citation[];
  activeCitation: number | null;
  onCite: (n: number) => void;
  streaming?: boolean;
}

function CitationBadge({
  n,
  citation,
  active,
  onCite,
}: {
  n: number;
  citation: Citation | undefined;
  active: boolean;
  onCite: (n: number) => void;
}) {
  const label = citation
    ? `Source ${n}: ${citation.act} section ${citation.section_number}`
    : `Source ${n}`;
  return (
    <button
      type="button"
      onClick={() => onCite(n)}
      disabled={!citation}
      aria-label={label}
      title={citation ? `${citation.act} § ${citation.section_number}${citation.section_title ? ` — ${citation.section_title}` : ""}` : undefined}
      className={`mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded px-1 align-middle font-sans text-[0.7rem] font-bold transition-colors ${
        active
          ? "bg-saffron-500 text-navy-950"
          : "bg-navy-100 text-navy-700 hover:bg-saffron-200 hover:text-navy-900 disabled:hover:bg-navy-100 dark:bg-navy-700 dark:text-navy-100 dark:hover:bg-saffron-500/30"
      }`}
    >
      {n}
    </button>
  );
}

function renderInline(text: string, props: Props, keyPrefix: string): ReactNode[] {
  return text.split(INLINE_RE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={key} className="font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    const cite = /^\[(\d{1,3})\]$/.exec(part);
    if (cite) {
      const n = Number(cite[1]);
      return (
        <CitationBadge
          key={key}
          n={n}
          citation={props.citations.find((c) => c.n === n)}
          active={props.activeCitation === n}
          onCite={props.onCite}
        />
      );
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function AnswerText(props: Props) {
  const blocks = props.text.trim().split(/\n{2,}/);
  return (
    <div className="legal-text space-y-3 text-navy-900 dark:text-navy-50">
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const isList = lines.length > 0 && lines.every((l) => LIST_ITEM_RE.test(l));
        const last = b === blocks.length - 1;
        const caret = props.streaming && last && (
          <span className="ml-0.5 inline-block h-4 w-0.5 translate-y-0.5 animate-blink bg-saffron-500" aria-hidden />
        );
        if (isList) {
          const ordered = /^\s*\d/.test(lines[0] ?? "");
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={b} className={`space-y-1 pl-5 ${ordered ? "list-decimal" : "list-disc"} marker:text-saffron-500`}>
              {lines.map((line, i) => (
                <li key={i}>
                  {renderInline(line.replace(LIST_ITEM_RE, ""), props, `${b}-${i}`)}
                  {i === lines.length - 1 && caret}
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={b}>
            {lines.map((line, i) => (
              <Fragment key={i}>
                {i > 0 && <br />}
                {renderInline(line, props, `${b}-${i}`)}
              </Fragment>
            ))}
            {caret}
          </p>
        );
      })}
    </div>
  );
}
