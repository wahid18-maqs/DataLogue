// Secondary chart cards containing exactly up to 4 small cards/charts:
// - Bar chart for order counts or category totals
// - Line chart for customer counts over time
// - Donut/pie for top categories/products
// - Donut/radial-style distribution for status/payment
// - If a metric is unavailable, hides that card gracefully

import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ResizableCard from "./ResizableCard";
import { useChartTheme } from "./chartTheme";

function MiniTooltip({ active, payload, label }) {
  if (active && payload && payload.length) {
    const item = payload[0];
    return (
      <div className="rounded-lg border border-slate-200 bg-surface p-2 shadow-sm">
        <p className="text-[11px] font-semibold text-slate-700">{label || item.name}</p>
        <p className="text-[11px] font-medium text-blue-600">
          {typeof item.value === "number" ? item.value.toLocaleString() : item.value}
        </p>
      </div>
    );
  }
  return null;
}

function SmallChartCard({ chart }) {
  const chartTheme = useChartTheme();

  if (!chart || !chart.figure) return null;

  const { chart_type, title, figure } = chart;
  const trace = figure?.data?.[0] || {};

  let content = null;

  if (chart_type === "bar") {
    const xVals = trace.x || [];
    const yVals = trace.y || [];
    const data = xVals.map((x, i) => ({ name: String(x), value: yVals[i] ?? 0 }));

    content = (
      <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fontSize: 10, fill: chartTheme.tick }} interval={0} height={24} />
        <YAxis tick={{ fontSize: 10, fill: chartTheme.tick }} />
        <Tooltip content={<MiniTooltip />} />
        <Bar dataKey="value" fill={chartTheme.series[0]} radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    );
  } else if (chart_type === "line") {
    const xVals = trace.x || [];
    const yVals = trace.y || [];
    const data = xVals.map((x, i) => ({ name: String(x), value: yVals[i] ?? 0 }));

    content = (
      <LineChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <XAxis dataKey="name" tick={{ fontSize: 10, fill: chartTheme.tick }} interval="preserveStartEnd" height={24} />
        <YAxis tick={{ fontSize: 10, fill: chartTheme.tick }} />
        <Tooltip content={<MiniTooltip />} />
        <Line type="monotone" dataKey="value" stroke={chartTheme.series[0]} strokeWidth={2} dot={{ r: 2.5, fill: chartTheme.series[0] }} />
      </LineChart>
    );
  } else if (chart_type === "pie") {
    const labels = trace.labels || [];
    const values = trace.values || [];
    const data = labels.map((l, i) => ({ name: String(l), value: values[i] ?? 0 }));

    content = (
      <PieChart margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <Tooltip content={<MiniTooltip />} />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} iconSize={8} />
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={28}
          outerRadius={48}
          paddingAngle={2}
        >
          {data.map((_, index) => (
            <Cell key={`cell-${index}`} fill={chartTheme.pie[index % chartTheme.pie.length]} />
          ))}
        </Pie>
      </PieChart>
    );
  }

  if (!content) return null;

  return (
    <ResizableCard
      storageKey={`secondary-${title}`}
      title={title}
      className="min-w-0"
      min={{ width: 220, height: 180 }}
      max={{ width: 1200, height: 1000 }}
      lockWidth
    >
      <div className="flex h-full flex-col justify-between rounded-xl border border-slate-200/80 bg-surface p-3.5 shadow-sm">
        <div className="mb-1">
          <h3 className="truncate text-xs font-semibold text-slate-800" title={title}>
            {title}
          </h3>
        </div>
        <div className="h-[180px] min-h-[120px] w-full flex-1">
          <ResponsiveContainer width="100%" height="100%">
            {content}
          </ResponsiveContainer>
        </div>
      </div>
    </ResizableCard>
  );
}

export default function SecondaryCharts({ charts = [], kpis = [] }) {
  // Cap at exactly 4 small cards maximum
  const validCharts = (charts || []).filter((c) => c && c.figure).slice(0, 4);

  // If there are fewer than 4 charts, we can gracefully complement with KPI cards if available
  const totalSlots = 4;
  const cardsNeeded = totalSlots - validCharts.length;
  const extraKpis = (kpis || []).slice(0, cardsNeeded);

  if (validCharts.length === 0 && extraKpis.length === 0) {
    return null;
  }

  return (
    <>
      {validCharts.map((chart, idx) => (
        <SmallChartCard key={`${chart.title}-${idx}`} chart={chart} />
      ))}

      {validCharts.length < 4 &&
        extraKpis.map((kpi, idx) => (
          <ResizableCard
            key={`${kpi.label}-${idx}`}
            storageKey={`kpi-${kpi.label}`}
            title={kpi.label}
            className="min-w-0"
            min={{ width: 220, height: 160 }}
            max={{ width: 1200, height: 1000 }}
            lockWidth
          >
            <div className="flex h-full flex-col justify-between rounded-xl border border-slate-200/80 bg-surface p-3.5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                {kpi.label}
              </p>
              <div className="my-auto py-2">
                <span className="text-2xl font-bold tracking-tight text-slate-900">
                  {kpi.formatted || kpi.value}
                </span>
              </div>
              <p className="text-[11px] text-slate-400">Derived from active dataset</p>
            </div>
          </ResizableCard>
        ))}
    </>
  );
}
