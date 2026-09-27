/** recharts visualisations for evaluation runs (theme-aware). */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useTheme } from "../../hooks/useTheme";
import type { ModeMetrics, RetrievalMode, ThresholdReport } from "../../types/api";

export const MODE_LABELS: Record<RetrievalMode, string> = {
  vector: "Vector",
  keyword: "Keyword",
  hybrid: "Hybrid",
  hybrid_rerank: "Hybrid + re-rank",
};

const SERIES = ["#f18212", "#4a5f89", "#10b981", "#97a8c8"];

function useChartTheme() {
  const { isDark } = useTheme();
  return {
    grid: isDark ? "#243559" : "#e3e8f2",
    axis: isDark ? "#97a8c8" : "#4a5f89",
    tooltip: {
      backgroundColor: isDark ? "#101a33" : "#ffffff",
      border: `1px solid ${isDark ? "#243559" : "#e3e8f2"}`,
      borderRadius: 8,
      color: isDark ? "#e3e8f2" : "#101a33",
      fontSize: 12,
    },
  };
}

interface Series {
  key: keyof ModeMetrics;
  label: string;
}

export function ModeBarChart({
  modes,
  series,
  unit,
  percent = false,
}: {
  modes: Partial<Record<RetrievalMode, ModeMetrics>>;
  series: Series[];
  unit?: string;
  percent?: boolean;
}) {
  const theme = useChartTheme();
  const data = (Object.keys(modes) as RetrievalMode[]).map((mode) => {
    const row: Record<string, string | number | null> = { mode: MODE_LABELS[mode] };
    for (const s of series) {
      const value = modes[mode]?.[s.key];
      row[s.label] = typeof value === "number" ? (percent ? Math.round(value * 1000) / 10 : Math.round(value)) : null;
    }
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap="22%">
        <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
        <XAxis dataKey="mode" tick={{ fill: theme.axis, fontSize: 12 }} tickLine={false} axisLine={{ stroke: theme.grid }} />
        <YAxis
          tick={{ fill: theme.axis, fontSize: 12 }}
          tickLine={false}
          axisLine={false}
          domain={percent ? [0, 100] : [0, "auto"]}
          unit={percent ? "%" : unit}
        />
        <Tooltip
          contentStyle={theme.tooltip}
          cursor={{ fill: theme.grid, opacity: 0.4 }}
          formatter={(value) => (value == null ? "–" : `${value}${percent ? "%" : unit ?? ""}`)}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: theme.axis }} />
        {series.map((s, i) => (
          <Bar key={s.label} dataKey={s.label} fill={SERIES[i % SERIES.length]} radius={[4, 4, 0, 0]} maxBarSize={36} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ThresholdChart({ report }: { report: ThresholdReport }) {
  const theme = useChartTheme();
  const data = report.curve.map((p) => ({
    threshold: p.threshold,
    "Balanced accuracy": Math.round(p.balanced_accuracy * 100),
    "Answer recall": Math.round(p.answer_recall * 100),
    "Refusal recall": Math.round(p.refusal_recall * 100),
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
        <XAxis
          dataKey="threshold"
          type="number"
          domain={[0, 1]}
          tick={{ fill: theme.axis, fontSize: 12 }}
          tickLine={false}
          axisLine={{ stroke: theme.grid }}
        />
        <YAxis tick={{ fill: theme.axis, fontSize: 12 }} tickLine={false} axisLine={false} domain={[0, 100]} unit="%" />
        <Tooltip contentStyle={theme.tooltip} formatter={(v) => `${v}%`} labelFormatter={(l) => `Threshold ${l}`} />
        <Legend wrapperStyle={{ fontSize: 12, color: theme.axis }} />
        {report.recommended !== null && (
          <ReferenceLine x={report.recommended} stroke="#f18212" strokeDasharray="4 4" label={{ value: "recommended", fill: "#f18212", fontSize: 11, position: "top" }} />
        )}
        <ReferenceLine x={report.current} stroke={theme.axis} strokeDasharray="2 4" label={{ value: "current", fill: theme.axis, fontSize: 11, position: "insideTopRight" }} />
        <Line type="monotone" dataKey="Balanced accuracy" stroke={SERIES[0]} strokeWidth={2.5} dot={false} />
        <Line type="monotone" dataKey="Answer recall" stroke={SERIES[1]} strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="Refusal recall" stroke={SERIES[2]} strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
