// Card of headline stat pills (Total Sales, Avg Order Value, …), each with an
// optional trend indicator. Rendered between the dashboard charts and the
// Recent Orders & Activity table.

export default function QuickStatsCard({ stats = [], title = "Key Metrics" }) {
  if (!stats.length) return null;

  return (
    <section className="rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
      <h2 className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-400">
        {title}
      </h2>

      <div className="flex flex-wrap items-center gap-2">
        {stats.map((stat, idx) => (
          <div
            key={`${stat.label}-${idx}`}
            className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50/80 px-3.5 py-1.5 text-xs text-slate-700 shadow-none transition-colors hover:bg-slate-100"
          >
            <span className="font-medium text-slate-500">{stat.label}:</span>
            <span className="font-semibold text-slate-900">{stat.value}</span>
            {stat.trend && (
              <span
                className={`inline-flex items-center font-semibold text-[11px] ${
                  stat.trend_direction === "down" ? "text-rose-600" : "text-emerald-600"
                }`}
              >
                {stat.trend}
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
