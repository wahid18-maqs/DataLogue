// Renders a single slide from the backend deck plan onto a 16:9 white canvas.
//
// The deck plan returned by POST /presentations/generate describes exactly the
// slides that the backend materialises into the .pptx file, so this canvas is
// a faithful preview of the real presentation (no fake slides).
//
// The slide is authored at a fixed 1280x720 design size. Callers scale that
// box to fit their space (see SlidePreview and SlideThumbnailRail), so the
// slide keeps its proportions and reads like a real slide at any size.
//
// When `editing` is on, the slide's own text becomes editable in place: the
// requester clicks a heading, a finding or a bullet and types directly on the
// slide, exactly where it will appear in the exported file. The text keeps the
// slide's own typography, so editing never changes the layout.

import { useLayoutEffect, useRef } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { DEFAULT_PALETTE, seriesColors } from "./slideTheme";

// The slide's design size, in CSS pixels. Everything inside is sized against
// this so a scaled copy stays proportionally identical.
export const SLIDE_DESIGN_WIDTH = 1280;
export const SLIDE_DESIGN_HEIGHT = 720;

function formatValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * A piece of slide text that the requester can edit in place.
 *
 * It is a plain element when the deck is not being edited, and a
 * contentEditable element of the same shape when it is — so toggling the
 * editor never moves the text on the slide.
 *
 * The change is committed on every keystroke, not on blur: the requester may
 * go straight from typing to pressing *Save Changes*, and a commit that only
 * happened on blur would be lost.
 */
function Text({
  value = "",
  path,
  editing = false,
  onEdit,
  multiline = false,
  className = "",
  style,
  as: Tag = "div",
  ...rest
}) {
  const ref = useRef(null);
  const isFocused = useRef(false);

  // The contentEditable element is uncontrolled: React must not rewrite its
  // content while the requester is typing, or the caret jumps. The value is
  // pushed in when the text changes from outside (a regeneration) or when the
  // element is not being edited.
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || isFocused.current) return;
    const current = node.innerText;
    if (current !== String(value ?? "")) {
      node.innerText = String(value ?? "");
    }
  }, [value, editing]);

  if (!editing) {
    return (
      <Tag className={className} style={style} {...rest}>
        {value}
      </Tag>
    );
  }

  const commit = (event) => {
    // innerText keeps the browser's own line breaks; a trailing one is the
    // caret sitting at the end of the text, not part of it.
    const text = event.currentTarget.innerText.replace(/\n+$/, "");
    if (text !== String(value ?? "")) onEdit?.(path, text);
  };

  return (
    <Tag
      ref={ref}
      className={`${className} rounded-sm outline-none ring-offset-page focus:ring-2 focus:ring-blue-400/70 hover:ring-1 hover:ring-blue-300/60`}
      style={{ ...style, cursor: "text" }}
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      role="textbox"
      aria-label={path ? `Edit ${path.join(".")}` : "Edit text"}
      onFocus={() => {
        isFocused.current = true;
      }}
      onBlur={(event) => {
        isFocused.current = false;
        commit(event);
      }}
      onInput={commit}
      onKeyDown={(event) => {
        // Enter commits a single-line field; Shift+Enter makes a new line in
        // a multi-line one. Escape leaves the field.
        if (event.key === "Enter" && !multiline && !event.shiftKey) {
          event.preventDefault();
          event.currentTarget.blur();
        }
        if (event.key === "Escape") {
          event.currentTarget.blur();
        }
      }}
      {...rest}
    />
  );
}

function Header({ slide, editing, onEdit, palette }) {
  return (
    <>
      <Text
        as="p"
        className="text-[13px] font-bold uppercase tracking-[0.12em]"
        style={{ color: palette.primary }}
        value={(slide.category || "Executive Briefing").toUpperCase()}
        path={["category"]}
        editing={editing}
        onEdit={onEdit}
      />
      <Text
        as="h2"
        className="mt-[6px] text-[30px] font-bold leading-tight"
        style={{ color: palette.text_main }}
        value={slide.title}
        path={["title"]}
        editing={editing}
        onEdit={onEdit}
      />
    </>
  );
}

function ChartBody({ slide, palette, seriesPalette }) {
  const data = (slide.categories || []).map((category, index) => {
    const point = { name: String(category) };
    (slide.series || []).forEach((series, seriesIndex) => {
      point[`s${seriesIndex}`] = series.values[index];
    });
    return point;
  });

  const series = slide.series || [];
  if (!data.length || !series.length) {
    return (
      <div className="flex h-full items-center justify-center text-[14px] text-slate-400">
        No chart data available
      </div>
    );
  }

  const axisTick = { fontSize: 13, fill: palette.text_muted };
  const gridStroke = palette.border;

  return (
    <ResponsiveContainer width="100%" height="100%">
      {slide.chart_type === "line" ? (
        <LineChart data={data} margin={{ top: 16, right: 28, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
          <XAxis dataKey="name" tick={axisTick} tickLine={false} axisLine={{ stroke: gridStroke }} />
          <YAxis tick={axisTick} tickLine={false} axisLine={{ stroke: gridStroke }} width={64} />
          <Tooltip
            formatter={(value) => formatValue(value)}
            contentStyle={{
              fontSize: 13,
              borderRadius: 8,
              border: `1px solid ${gridStroke}`,
            }}
          />
          {series.map((s, index) => (
            <Line
              key={s.name}
              type="monotone"
              dataKey={`s${index}`}
              name={s.name}
              stroke={seriesPalette[index % seriesPalette.length]}
              strokeWidth={3}
              dot={{ r: 4 }}
            />
          ))}
          {slide.legend && <Legend wrapperStyle={{ fontSize: 14 }} iconType="circle" iconSize={10} />}
        </LineChart>
      ) : (
        <BarChart
          data={data}
          layout={slide.chart_type === "bar" ? "vertical" : "horizontal"}
          margin={{ top: 16, right: 28, bottom: 8, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
          {slide.chart_type === "bar" ? (
            <>
              <XAxis type="number" tick={axisTick} tickLine={false} axisLine={{ stroke: gridStroke }} />
              <YAxis
                type="category"
                dataKey="name"
                tick={axisTick}
                tickLine={false}
                axisLine={{ stroke: gridStroke }}
                width={160}
              />
            </>
          ) : (
            <>
              <XAxis dataKey="name" tick={axisTick} tickLine={false} axisLine={{ stroke: gridStroke }} />
              <YAxis tick={axisTick} tickLine={false} axisLine={{ stroke: gridStroke }} width={64} />
            </>
          )}
          <Tooltip
            formatter={(value) => formatValue(value)}
            contentStyle={{
              fontSize: 13,
              borderRadius: 8,
              border: `1px solid ${gridStroke}`,
            }}
          />
          {series.map((s, seriesIndex) => (
            <Bar
              key={s.name}
              dataKey={`s${seriesIndex}`}
              name={s.name}
              radius={slide.chart_type === "bar" ? [0, 4, 4, 0] : [4, 4, 0, 0]}
              fill={seriesPalette[seriesIndex % seriesPalette.length]}
            />
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}

function TitleSlide({ slide, editing, onEdit, palette }) {
  const kpis = slide.kpis || [];

  return (
    <div className="flex h-full flex-col">
      <div className="h-[10px] w-full" style={{ background: palette.primary }} />
      <div className="flex flex-1 flex-col px-[6%] pt-[6%]">
        <Text
          as="h2"
          className="text-[42px] font-bold leading-tight"
          style={{ color: palette.text_main }}
          value={slide.title}
          path={["title"]}
          editing={editing}
          onEdit={onEdit}
        />
        <Text
          as="p"
          className="mt-[10px] text-[16px]"
          style={{ color: palette.text_muted }}
          value={slide.subtitle}
          path={["subtitle"]}
          editing={editing}
          onEdit={onEdit}
        />

        <div className="mt-[6%] grid grid-cols-4 gap-[2.5%]">
          {kpis.map((kpi) => (
            <div
              key={kpi.label}
              className="rounded-xl border px-[10%] py-[14px]"
              style={{ background: palette.card_bg, borderColor: palette.border }}
            >
              <p
                className="text-[13px] font-bold uppercase tracking-[0.08em]"
                style={{ color: palette.text_muted }}
              >
                {kpi.label}
              </p>
              <p
                className="mt-[6px] text-[30px] font-bold leading-none"
                style={{ color: palette.primary }}
              >
                {kpi.value}
              </p>
              <p className="mt-[8px] text-[13px] leading-snug" style={{ color: palette.text_muted }}>
                {kpi.caption}
              </p>
            </div>
          ))}
        </div>

        <div
          className="mt-auto mb-[6%] rounded-xl px-[3.5%] py-[3%]"
          style={{ background: palette.bg_dark }}
        >
          <Text
            as="p"
            className="text-[13px] font-bold uppercase tracking-[0.1em]"
            style={{ color: palette.secondary }}
            value={(slide.banner_label || "Executive Summary Highlight").toUpperCase()}
            path={["banner_label"]}
            editing={editing}
            onEdit={onEdit}
          />
          <Text
            as="p"
            className="mt-[8px] text-[17px] leading-relaxed"
            style={{ color: palette.on_dark }}
            value={slide.banner_text}
            path={["banner_text"]}
            editing={editing}
            onEdit={onEdit}
            multiline
          />
        </div>
      </div>
    </div>
  );
}

function SummarySlide({ slide, editing, onEdit, palette }) {
  return (
    <div className="flex h-full flex-col px-[6%] pt-[5%]">
      <Header slide={slide} editing={editing} onEdit={onEdit} palette={palette} />
      <div className="mt-[3.5%] flex flex-1 flex-col gap-[2.5%]">
        {(slide.findings || []).map((finding, index) => (
          <div
            key={index}
            className="flex items-start gap-[2%] rounded-xl border px-[2.5%] py-[2%]"
            style={{ background: palette.card_bg, borderColor: palette.border }}
          >
            <span
              className="mt-[6px] h-full w-[4px] shrink-0 rounded-full"
              style={{ background: palette.primary }}
            />
            <div className="min-w-0">
              <Text
                as="p"
                className="text-[19px] font-bold leading-snug"
                style={{ color: palette.text_main }}
                value={finding.title}
                path={["findings", index, "title"]}
                editing={editing}
                onEdit={onEdit}
              />
              <Text
                as="p"
                className="mt-[6px] text-[15px] leading-relaxed"
                style={{ color: palette.text_muted }}
                value={finding.desc}
                path={["findings", index, "desc"]}
                editing={editing}
                onEdit={onEdit}
                multiline
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChartSlide({ slide, editing, onEdit, palette, seriesPalette }) {
  const caption = (slide.caption || "").trim();
  return (
    <div className="flex h-full flex-col px-[6%] pt-[5%]">
      <Header slide={slide} editing={editing} onEdit={onEdit} palette={palette} />
      <div className={`min-h-0 flex-1 ${caption ? "pb-[3%]" : ""}`}>
        <ChartBody slide={slide} palette={palette} seriesPalette={seriesPalette} />
      </div>
      {caption && (
        <Text
          as="p"
          className="text-[15px] italic leading-snug"
          style={{ color: palette.text_muted }}
          value={caption}
          path={["caption"]}
          editing={editing}
          onEdit={onEdit}
          multiline
        />
      )}
    </div>
  );
}

function InsightsSlide({ slide, editing, onEdit, palette }) {
  return (
    <div className="flex h-full flex-col px-[6%] pt-[5%]">
      <Header slide={slide} editing={editing} onEdit={onEdit} palette={palette} />
      <div className="mt-[3.5%] grid min-h-0 flex-1 grid-cols-2 gap-[3%]">
        <div
          className="rounded-xl border px-[2.5%] py-[2.5%]"
          style={{ background: palette.card_bg, borderColor: palette.border }}
        >
          <p
            className="text-[14px] font-bold uppercase tracking-[0.08em]"
            style={{ color: palette.primary }}
          >
            Core Empirical Observations
          </p>
          <ul className="mt-[3%] space-y-[2.5%]">
            {(slide.insights || []).map((insight, index) => (
              <li
                key={index}
                className="text-[15px] leading-relaxed"
                style={{ color: palette.text_main }}
              >
                <span aria-hidden="true">• </span>
                <Text
                  as="span"
                  value={insight}
                  path={["insights", index]}
                  editing={editing}
                  onEdit={onEdit}
                  multiline
                />
              </li>
            ))}
          </ul>
        </div>
        <div
          className="rounded-xl px-[2.5%] py-[2.5%]"
          style={{ background: palette.bg_dark }}
        >
          <p
            className="text-[14px] font-bold uppercase tracking-[0.08em]"
            style={{ color: palette.secondary }}
          >
            Recommended Next Actions
          </p>
          <ul className="mt-[3%] space-y-[2.5%]">
            {(slide.recommendations || []).map((rec, index) => (
              <li
                key={index}
                className="text-[15px] leading-relaxed"
                style={{ color: palette.on_dark }}
              >
                <span aria-hidden="true">→ </span>
                <Text
                  as="span"
                  value={rec}
                  path={["recommendations", index]}
                  editing={editing}
                  onEdit={onEdit}
                  multiline
                />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function SlideCanvas({
  slide,
  editing = false,
  onEdit,
  palette = DEFAULT_PALETTE,
  themeName = null,
  seriesPalette: seriesPaletteProp = null,
}) {
  if (!slide) return null;

  const seriesPalette = seriesPaletteProp || seriesColors(null, themeName);

  const body = {
    title: <TitleSlide slide={slide} editing={editing} onEdit={onEdit} palette={palette} />,
    summary: (
      <SummarySlide slide={slide} editing={editing} onEdit={onEdit} palette={palette} />
    ),
    chart: (
      <ChartSlide
        slide={slide}
        editing={editing}
        onEdit={onEdit}
        palette={palette}
        seriesPalette={seriesPalette}
      />
    ),
    insights: (
      <InsightsSlide slide={slide} editing={editing} onEdit={onEdit} palette={palette} />
    ),
  }[slide.type];

  return (
    <div
      className="flex h-full w-full flex-col"
      style={{
        width: SLIDE_DESIGN_WIDTH,
        height: SLIDE_DESIGN_HEIGHT,
        background: palette.card_bg,
      }}
    >
      {body}
    </div>
  );
}
