import { BarChart3, FlaskConical, type LucideIcon } from "lucide-react";

function ComingSoon({ icon: Icon, title, points }: { icon: LucideIcon; title: string; points: string[] }) {
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
        <div className="card p-8 text-center">
          <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-saffron-100 text-saffron-600 dark:bg-saffron-500/15 dark:text-saffron-300">
            <Icon className="size-7" aria-hidden />
          </div>
          <h1 className="mt-5 font-serif text-2xl font-bold">{title}</h1>
          <p className="mt-2 text-sm text-navy-600 dark:text-navy-300">This screen arrives in a later phase. It will show:</p>
          <ul className="mx-auto mt-5 max-w-md space-y-2 text-left text-sm text-navy-700 dark:text-navy-200">
            {points.map((p) => (
              <li key={p} className="flex gap-2">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-saffron-500" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export function EvaluationPage() {
  return (
    <ComingSoon
      icon={FlaskConical}
      title="Evaluation"
      points={[
        "Run the golden-set evaluation as a background job",
        "Compare vector, keyword, hybrid and hybrid + re-rank: recall@5, MRR, faithfulness, latency",
        "Bar charts and the history of previous runs",
      ]}
    />
  );
}

export function AnalyticsPage() {
  return (
    <ComingSoon
      icon={BarChart3}
      title="Analytics"
      points={[
        "Queries per day, refusal rate and average latency",
        "Cache hit rate and guardrail flag counts",
        "Top questions and the helpful / not helpful feedback ratio",
      ]}
    />
  );
}
