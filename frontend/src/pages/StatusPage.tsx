import { StatusBadge } from "../components/StatusBadge";
import { useReadiness } from "../hooks/useReadiness";

const DEPENDENCY_LABELS: Record<string, string> = {
  database: "PostgreSQL (pgvector)",
  redis: "Redis",
};

export function StatusPage() {
  const { state, refresh } = useReadiness();

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-4 py-12">
      <header className="mb-8">
        <p className="text-sm font-semibold tracking-wide text-saffron-600 uppercase dark:text-saffron-400">
          DharaDrishti
        </p>
        <h1 className="font-serif text-3xl font-bold text-navy-900 dark:text-navy-50">
          System status
        </h1>
        <p className="mt-2 text-navy-700 dark:text-navy-300">
          Live readiness of the backend services.
        </p>
      </header>

      <section
        aria-labelledby="readiness-heading"
        aria-busy={state.kind === "loading"}
        className="rounded-xl border border-navy-100 bg-white p-6 shadow-sm dark:border-navy-800 dark:bg-navy-900"
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 id="readiness-heading" className="text-lg font-semibold">
            API readiness
          </h2>
          {state.kind === "success" && <StatusBadge ok={state.data.status === "ok"} />}
        </div>

        <div aria-live="polite">
          {state.kind === "loading" && (
            <ul className="space-y-3" aria-label="Loading status">
              {[0, 1].map((i) => (
                <li key={i} className="h-10 animate-pulse rounded-md bg-navy-100 dark:bg-navy-800" />
              ))}
            </ul>
          )}

          {state.kind === "error" && (
            <div role="alert" className="rounded-md bg-red-50 p-4 text-red-900 dark:bg-red-900/30 dark:text-red-100">
              <p className="font-medium">Couldn't check the API.</p>
              <p className="mt-1 text-sm">{state.error.message}</p>
              {state.error.requestId && (
                <p className="mt-1 text-xs opacity-80">Request ID: {state.error.requestId}</p>
              )}
            </div>
          )}

          {state.kind === "success" &&
            (Object.keys(state.data.checks).length === 0 ? (
              <p className="text-navy-700 dark:text-navy-300">No dependencies reported.</p>
            ) : (
              <ul className="divide-y divide-navy-100 dark:divide-navy-800">
                {Object.entries(state.data.checks).map(([name, check]) => (
                  <li key={name} className="flex items-center justify-between gap-4 py-3">
                    <div>
                      <p className="font-medium">{DEPENDENCY_LABELS[name] ?? name}</p>
                      <p className="text-sm text-navy-700 dark:text-navy-300">
                        {check.status === "ok" ? `${check.latency_ms.toFixed(1)} ms` : check.error}
                      </p>
                    </div>
                    <StatusBadge ok={check.status === "ok"} />
                  </li>
                ))}
              </ul>
            ))}
        </div>

        <button
          type="button"
          onClick={refresh}
          disabled={state.kind === "loading"}
          className="mt-6 rounded-md bg-navy-800 px-4 py-2 font-medium text-white hover:bg-navy-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-saffron-500 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-saffron-500 dark:text-navy-950 dark:hover:bg-saffron-400"
        >
          {state.kind === "loading" ? "Checking…" : "Check again"}
        </button>
      </section>
    </main>
  );
}
