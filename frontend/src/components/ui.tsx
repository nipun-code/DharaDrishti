/** Small presentational building blocks shared across pages. */

import { Scale, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import type { ActStatus } from "../types/api";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="grid size-8 place-items-center rounded-lg bg-saffron-500 text-navy-950 shadow-sm">
        <Scale className="size-4.5" aria-hidden />
      </span>
      {!compact && (
        <span className="font-serif text-lg font-bold tracking-tight">
          Dhara<span className="text-saffron-500">Drishti</span>
        </span>
      )}
    </span>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`}
    />
  );
}

export function ActBadge({ code, status }: { code: string; status?: ActStatus }) {
  const repealed = status === "repealed";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold tracking-wide ${
        repealed
          ? "bg-navy-100 text-navy-500 line-through decoration-1 dark:bg-navy-800 dark:text-navy-400"
          : "bg-saffron-100 text-saffron-700 dark:bg-saffron-500/15 dark:text-saffron-300"
      }`}
      title={repealed ? `${code} (repealed)` : code}
    >
      {code}
    </span>
  );
}

export function RepealedTag() {
  return (
    <span className="rounded-md bg-red-100 px-1.5 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wide text-red-800 dark:bg-red-900/40 dark:text-red-200">
      Repealed
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="grid size-12 place-items-center rounded-full bg-navy-100 text-navy-500 dark:bg-navy-800 dark:text-navy-300">
        {icon}
      </div>
      <h3 className="font-serif text-lg font-semibold">{title}</h3>
      {children && <div className="max-w-md text-sm text-navy-600 dark:text-navy-300">{children}</div>}
      {action}
    </div>
  );
}

export function SkeletonLines({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-3.5" style={{ width: `${100 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

/** Right-hand slide-over panel. Closes on Escape and backdrop click; focuses itself on open. */
export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close panel"
        className="absolute inset-0 animate-fade-in bg-navy-950/40 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <div
        ref={panel}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-xl animate-slide-in-right flex-col bg-white shadow-2xl outline-none dark:bg-navy-900"
      >
        <div className="flex items-start justify-between gap-4 border-b border-navy-100 px-5 py-4 dark:border-navy-800">
          <div className="min-w-0">{title}</div>
          <button type="button" onClick={onClose} className="btn-ghost -mr-2 p-2" aria-label="Close">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
