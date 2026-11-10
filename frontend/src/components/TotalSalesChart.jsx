// Large Total Sells / Main Trend Chart component:
// - White background, 12px border radius, subtle border/shadow
// - Large responsive chart (multi-series or single line/area)
// - Title "Total sells" / dynamic title
// - Subtitle
// - Date/filter interactive control
// - Driven entirely by dashboard API payload

import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ResizableCard from "./ResizableCard";
import { useChartTheme } from "./chartTheme";

function formatYAxis(val) {
  if (typeof val !== "number") return val;
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1_000) return `${(val / 1_000).toFixed(0)}k`;
  return val.toLocaleString();
}

function CustomTooltip({ active, payload, label }) {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-lg border border-slate-200 bg-surface p-3 shadow-md">
        <p className="mb-1 text-xs font-semibold text-slate-700">{label}</p>
        {payload.map((entry, index) => (
          <p key={`item-${index}`} className="text-xs" style={{ color: entry.color }}>
            <span className="font-medium">{entry.name}: </span>
            <span className="font-semibold">
              {typeof entry.value === "number" ? entry.value.toLocaleString() : entry.value}
            </span>
          </p>
        ))}
      </div>
    );
  }
  return null;
}

export default function TotalSalesChart({ chart }) {
  const [filterPeriod, setFilterPeriod] = useState("All");
  const chartTheme = useChartTheme();

  if (!chart || !chart.figure) {
    return (
      <div className="flex h-96 items-center justify-center rounded-xl border border-slate-200 bg-surface p-6 shadow-sm">
        <p className="text-sm text-slate-400">Main chart data not available</p>
      </div>
    );
  }

  const traces = chart.figure.data || [];

  // Build unified rows from Plotly traces: array of { period, series1, series2, ... }
  let data = [];
  const seriesKeys = [];

  const traceKey = (trace, idx) => trace.name || `Series ${idx + 1}`;
  const firstTraceWithValues = traces.find((trace) => (trace.x?.length || trace.y?.length));
  const xVals = firstTraceWithValues?.x?.length
    ? firstTraceWithValues.x
    : (firstTraceWithValues?.y || []).map((_, index) => index + 1);
  traces.forEach((trace, idx) => {
    const keyName = traceKey(trace, idx);
    seriesKeys.push({ key: keyName, color: chartTheme.series[idx % chartTheme.series.length] });
  });

  data = xVals.map((x, i) => {
    const row = { name: String(x) };
    traces.forEach((trace, idx) => {
      const keyName = traceKey(trace, idx);
      const value = Number(trace.y?.[i]);
      row[keyName] = Number.isFinite(value) ? value : null;
    });
    return row;
  });

  // Handle client-side filter control simulation (Last 30 days, 90 days, All)
  let displayedData = data;
  if (filterPeriod === "30D" && data.length > 5) {
    displayedData = data.slice(-5);
  } else if (filterPeriod === "90D" && data.length > 10) {
    displayedData = data.slice(-10);
  }

  const chartTitle = chart.title || "Total sells";

  return (
    <ResizableCard
      storageKey="main-chart"
      title="Total sells"
      className="min-w-0"
      min={{ width: 320, height: 260 }}
      max={{ width: 2000, height: 1400 }}
      lockWidth
    >
      <div className="flex h-full flex-col justify-between rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
        {/* Top Header & Controls */}
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold tracking-tight text-slate-800">
                Total sells
              </h2>
              <span className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
                {chartTitle}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-slate-500">
              Payment & transaction volume over time
            </p>
          </div>

          {/* Date / Filter Controls */}
          <div className="flex items-center gap-1 self-start rounded-lg border border-slate-200 bg-slate-50 p-0.5 sm:self-auto">
            {["All", "90D", "30D"].map((period) => (
              <button
                key={period}
                type="button"
                onClick={() => setFilterPeriod(period)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-all ${
                  filterPeriod === period
                    ? "bg-surface text-blue-600 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {period}
              </button>
            ))}
          </div>
        </div>

        {/* Main Chart Area */}
        <div className="h-[320px] min-h-[200px] w-full flex-1 pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={displayedData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: chartTheme.tick }} axisLine={{ stroke: chartTheme.axis }} />
              <YAxis tick={{ fontSize: 11, fill: chartTheme.tick }} tickFormatter={formatYAxis} axisLine={false} />
              <Tooltip content={<CustomTooltip />} />
              {seriesKeys.length > 1 && <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />}
              {seriesKeys.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={2.5}
                  dot={{ r: 2 }}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </ResizableCard>
  );
}
