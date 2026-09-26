interface StatusBadgeProps {
  ok: boolean;
  label?: string;
}

export function StatusBadge({ ok, label }: StatusBadgeProps) {
  const text = label ?? (ok ? "Healthy" : "Unavailable");
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-medium " +
        (ok
          ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
          : "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200")
      }
    >
      <span aria-hidden="true">{ok ? "●" : "▲"}</span>
      {text}
    </span>
  );
}
