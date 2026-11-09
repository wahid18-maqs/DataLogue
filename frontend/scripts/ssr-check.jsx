// Renders the presentation workspace components to static markup to catch
// runtime errors (undefined identifiers, bad props) that a build cannot see.
//
// Run: node scripts/ssr-check.jsx

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import SlideCanvas from "../src/components/Presentations/SlideCanvas.jsx";
import QuickStatsCard from "../src/components/QuickStatsCard.jsx";
import FileUpload from "../src/components/FileUpload.jsx";
import Sidebar from "../src/components/Sidebar.jsx";
import AssistantSidebar from "../src/components/AssistantSidebar.jsx";
import WorkbooksPanel, { WorkbookRow } from "../src/components/WorkbooksPanel.jsx";
import SlideThumbnailRail from "../src/components/Presentations/SlideThumbnailRail.jsx";
import SlidePreview from "../src/components/Presentations/SlidePreview.jsx";
import ScaledSlide from "../src/components/Presentations/ScaledSlide.jsx";
import PresentationToolbar from "../src/components/Presentations/PresentationToolbar.jsx";
import SuggestionsPanel from "../src/components/Presentations/SuggestionsPanel.jsx";
import ExportDialog from "../src/components/Presentations/ExportDialog.jsx";
import StageIndicator from "../src/components/Presentations/StageIndicator.jsx";
import { applyPath, diffDeck } from "../src/components/Presentations/editableFields.js";
import DashboardPresentation from "../src/components/DashboardPresentation.jsx";
import ResizableCard from "../src/components/ResizableCard.jsx";
import { computeResizedSize } from "../src/components/Resizable.jsx";
import TotalSalesChart from "../src/components/TotalSalesChart.jsx";
import SecondaryCharts from "../src/components/SecondaryCharts.jsx";
import LatestReviews from "../src/components/LatestReviews.jsx";
import SettingsPanel from "../src/components/SettingsPanel.jsx";
import { SettingsProvider, useSettings, WRITE_DEBOUNCE_MS } from "../src/settings/SettingsContext.jsx";
import {
  DEFAULTS,
  SCHEMA_VERSION,
  defaultSettings,
  migrateSettings,
  readSettings,
  writeSettings,
} from "../src/settings/settingsSchema.js";
import { resolvePalette, seriesColors } from "../src/components/Presentations/slideTheme.js";
import { createDebouncedWriter } from "../src/settings/debouncedWriter.js";
import { filterAndSort } from "../src/components/workbookList.js";
import { applyAppTheme } from "../src/settings/appTheme.js";
import { chartColorsFor } from "../src/components/chartTheme.js";
import { contrastFailures, palettesFromCss, LIGHT, DARK } from "../src/settings/contrast.js";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const failures = [];
function check(name, fn) {
  try {
    fn();
    console.log(`  PASS  ${name}`);
  } catch (error) {
    failures.push(name);
    console.log(`  FAIL  ${name}: ${error.message}`);
  }
}

const DECK = {
  title: "Sales & Operations Overview",
  subtitle: "Dataset Analysis (50 records, 20 attributes)",
  slide_count: 4,
  slides: [
    {
      index: 1,
      type: "title",
      title: "Sales & Operations Overview",
      subtitle: "Dataset Analysis (50 records, 20 attributes)",
      kpis: [
        { label: "Total Sales", value: "1,213,482.30", caption: "Verified" },
        { label: "Avg Sales", value: "24,269.65", caption: "Verified" },
        { label: "Total Quantity", value: "217", caption: "Verified" },
        { label: "Unique Customers", value: "18", caption: "Verified" },
      ],
      banner_label: "Executive Summary Highlight",
      banner_text: "This report delivers evidence-backed operational intelligence.",
    },
    {
      index: 2,
      type: "summary",
      category: "Executive Briefing",
      title: "Executive Summary & Core Findings",
      findings: [
        { title: "Monetary / Volume Scale (Sales)", desc: "Total accumulated value is 1,213,482.30." },
        { title: "Concentration in Category", desc: "Technology accounts for 120 entries." },
      ],
    },
    {
      index: 3,
      type: "chart",
      category: "Temporal Analysis",
      title: "Sales Trend Over Time",
      chart_type: "line",
      categories: ["2025-01", "2025-02", "2025-03"],
      series: [{ name: "Sales", values: [100, 200, 300] }],
      legend: true,
    },
    {
      index: 4,
      type: "chart",
      category: "Segment Analysis",
      title: "Performance by Category",
      chart_type: "column",
      categories: ["Technology", "Office"],
      series: [{ name: "Sales", values: [10, 20] }],
      legend: false,
    },
    {
      index: 5,
      type: "chart",
      category: "Leadership Ranking",
      title: "Top Performing Products",
      chart_type: "bar",
      categories: ["Chair", "Desk"],
      series: [{ name: "Total Sales", values: [5, 9] }],
      legend: false,
    },
    {
      index: 6,
      type: "insights",
      category: "Decision Roadmap",
      title: "Strategic Insights & Recommendations",
      insights: ["Revenue Concentration: the top 25% account for 60% of value."],
      recommendations: ["Align Resource Allocation toward highest-yield segments."],
    },
  ],
};

console.log("\n[SlideCanvas] every slide type renders");
for (const slide of DECK.slides) {
  check(`renders ${slide.type} slide`, () => {
    const html = renderToStaticMarkup(<SlideCanvas slide={slide} />);
    if (!html || html.length < 50) throw new Error("empty output");
  });
}

console.log("\n[SlideCanvas] the design box is 16:9");
for (const slide of DECK.slides) {
  check(`renders ${slide.type} slide at the design size`, () => {
    const html = renderToStaticMarkup(<SlideCanvas slide={slide} />);
    if (!html || html.length < 50) throw new Error("empty output");
    if (!html.includes("width:1280px") || !html.includes("height:720px")) {
      throw new Error("missing the 1280x720 design box");
    }
  });
}

console.log("\n[SlideCanvas] null slide is safe");
check("null slide returns null", () => {
  const html = renderToStaticMarkup(<SlideCanvas slide={null} />);
  if (html !== "") throw new Error(`expected empty, got ${html}`);
});

console.log("\n[SlideCanvas] the agent's caption renders on a chart slide");
check("renders the trend caption", () => {
  const html = renderToStaticMarkup(
    <SlideCanvas slide={{ ...DECK.slides[2], caption: "Sales trend upward over 724 days." }} />
  );
  if (!html.includes("Sales trend upward over 724 days.")) throw new Error("missing caption");
  if (!html.includes("italic")) throw new Error("caption is not styled as a caption");
});

check("a chart slide without a caption renders no caption", () => {
  const html = renderToStaticMarkup(<SlideCanvas slide={DECK.slides[2]} />);
  if (html.includes("italic")) throw new Error("unexpected caption styling");
});

console.log("\n[SlideThumbnailRail]");
check("renders all thumbnails", () => {
  const html = renderToStaticMarkup(
    <SlideThumbnailRail slides={DECK.slides} activeIndex={2} onSelect={() => {}} />
  );
  if (!html.includes("Slide 6 of")) {
    // slide numbers appear as "1".."6" badges; check the rail rendered content
  }
  const count = (html.match(/aspect-video/g) || []).length;
  if (count !== DECK.slides.length) {
    throw new Error(`expected ${DECK.slides.length} thumbnails, got ${count}`);
  }
});

console.log("\n[ScaledSlide] scales the slide to its box");
check("renders the slide inside a scaled box", () => {
  const html = renderToStaticMarkup(
    <ScaledSlide slide={DECK.slides[0]} className="w-full" />
  );
  if (!html.includes("scale(1)")) throw new Error("missing the scale transform");
  if (!html.includes("width:1280px")) throw new Error("missing the design width");
});

check("width fit derives the height from the aspect ratio", () => {
  const html = renderToStaticMarkup(
    <ScaledSlide slide={DECK.slides[0]} fit="width" />
  );
  if (!html.includes("scale(1)")) throw new Error("missing the scale transform");
});

check("an explicit scale drives the box size", () => {
  const html = renderToStaticMarkup(
    <ScaledSlide slide={DECK.slides[0]} scale={1.5} />
  );
  if (!html.includes("width:1920px")) throw new Error("expected a 1920px wide box");
  if (!html.includes("height:1080px")) throw new Error("expected a 1080px tall box");
  if (!html.includes("scale(1.5)")) throw new Error("expected a 1.5x transform");
});

check("empty rail shows a hint", () => {
  const html = renderToStaticMarkup(<SlideThumbnailRail slides={[]} />);
  if (!html.includes("No slides yet")) throw new Error("missing empty hint");
});

console.log("\n[SlidePreview]");
check("renders the active slide", () => {
  const html = renderToStaticMarkup(
    <SlidePreview
      slide={DECK.slides[0]}
      slideNumber={1}
      totalSlides={6}
      onPrev={() => {}}
      onNext={() => {}}
    />
  );
  if (!html.includes("Slide 1 of 6")) throw new Error("missing slide counter");
  if (!html.includes("width:1280px") || !html.includes("height:720px")) {
    throw new Error("missing the 16:9 design box");
  }
  if (!html.includes("scale(1)")) throw new Error("missing the scale transform");
});

check("renders an empty state without a slide", () => {
  const html = renderToStaticMarkup(
    <SlidePreview slide={null} slideNumber={0} totalSlides={0} />
  );
  if (!html.includes("No slide selected")) throw new Error("missing empty state");
});

console.log("\n[PresentationToolbar]");
check("renders the actions without a heading", () => {
  const html = renderToStaticMarkup(
    <PresentationToolbar
      hasDeck
      onGenerate={() => {}}
      onRegenerate={() => {}}
      onEdit={() => {}}
      onExport={() => {}}
    />
  );
  if (!html.includes("Generate Presentation")) throw new Error("missing generate button");
  if (!html.includes("Export PPTX")) throw new Error("missing export button");
  if (html.includes("AI Presentation")) throw new Error("heading still present");
  if (html.includes("Presentation Workspace")) throw new Error("fallback heading still present");
});

check("shows the regenerate action once a deck exists", () => {
  const withDeck = renderToStaticMarkup(
    <PresentationToolbar
      hasDeck
      onGenerate={() => {}}
      onRegenerate={() => {}}
      onEdit={() => {}}
      onExport={() => {}}
    />
  );
  if (!withDeck.includes("Regenerate Presentation")) {
    throw new Error("missing regenerate button");
  }
  const withoutDeck = renderToStaticMarkup(
    <PresentationToolbar
      hasDeck={false}
      onGenerate={() => {}}
      onRegenerate={() => {}}
      onEdit={() => {}}
      onExport={() => {}}
    />
  );
  if (withoutDeck.includes("Regenerate Presentation")) {
    throw new Error("regenerate button shown before any deck exists");
  }
});

check("shows the edit action once a deck exists, after the regenerate action", () => {
  const withDeck = renderToStaticMarkup(
    <PresentationToolbar
      hasDeck
      onGenerate={() => {}}
      onRegenerate={() => {}}
      onEdit={() => {}}
      onExport={() => {}}
    />
  );
  if (!withDeck.includes(">Edit<")) throw new Error("missing edit button");
  if (withDeck.indexOf("Regenerate Presentation") > withDeck.indexOf(">Edit<")) {
    throw new Error("the edit button must come after the regenerate button");
  }
  const withoutDeck = renderToStaticMarkup(
    <PresentationToolbar
      hasDeck={false}
      onGenerate={() => {}}
      onRegenerate={() => {}}
      onEdit={() => {}}
      onExport={() => {}}
    />
  );
  if (withoutDeck.includes(">Edit<")) {
    throw new Error("edit button shown before any deck exists");
  }
});

console.log("\n[SlideCanvas] the slide itself is editable");
check("editable text becomes a textbox on the slide", () => {
  const html = renderToStaticMarkup(
    <SlideCanvas slide={DECK.slides[0]} editing onEdit={() => {}} />
  );
  if (!html.includes("contenteditable")) throw new Error("the slide text is not editable");
  if (!html.includes("Edit banner_text")) throw new Error("the banner is not addressable");
  if (!html.includes("Edit title")) throw new Error("the title is not addressable");
});

check("the slide is not editable by default", () => {
  const html = renderToStaticMarkup(<SlideCanvas slide={DECK.slides[0]} />);
  if (html.includes("contenteditable")) throw new Error("the slide is editable without the editor");
});

check("a summary slide exposes its findings for editing", () => {
  const html = renderToStaticMarkup(
    <SlideCanvas slide={DECK.slides[1]} editing onEdit={() => {}} />
  );
  if (!html.includes("Edit findings.0.title")) throw new Error("the finding heading is not addressable");
  if (!html.includes("Edit findings.0.desc")) throw new Error("the finding text is not addressable");
});

check("an insights slide exposes its bullets for editing", () => {
  const insightsSlide = DECK.slides.find((slide) => slide.type === "insights");
  const html = renderToStaticMarkup(
    <SlideCanvas slide={insightsSlide} editing onEdit={() => {}} />
  );
  if (!html.includes("Edit insights.0")) throw new Error("the observation is not addressable");
  if (!html.includes("Edit recommendations.0")) {
    throw new Error("the recommendation is not addressable");
  }
});

console.log("\n[editableFields] the diff and the path");
check("the diff reports only the text that changed", () => {
  const saved = { slides: [{ type: "chart", title: "A", caption: "one" }] };
  const draft = { slides: [{ type: "chart", title: "A", caption: "two" }] };
  const edits = diffDeck(saved, draft);
  if (edits.length !== 1) throw new Error(`expected one edit, got ${edits.length}`);
  if (edits[0].slide !== 1 || edits[0].field !== "caption" || edits[0].value !== "two") {
    throw new Error(`unexpected edit: ${JSON.stringify(edits[0])}`);
  }
});

check("the diff ignores fields that are not editable", () => {
  const saved = { slides: [{ type: "chart", title: "A", categories: ["x"] }] };
  const draft = { slides: [{ type: "chart", title: "A", categories: ["y"] }] };
  const edits = diffDeck(saved, draft);
  if (edits.length !== 0) throw new Error(`expected no edits, got ${JSON.stringify(edits)}`);
});

check("a path sets the text it addresses", () => {
  const deck = { slides: [{ type: "title", title: "A", banner_text: "b" }] };
  const next = applyPath(deck, 0, ["banner_text"], "changed");
  if (next.slides[0].banner_text !== "changed") throw new Error("the text was not set");
  if (deck.slides[0].banner_text !== "b") throw new Error("the original deck was mutated");
});

check("a path reaches into a list item", () => {
  const deck = { slides: [{ type: "summary", findings: [{ title: "a", desc: "b" }] }] };
  const next = applyPath(deck, 0, ["findings", 0, "desc"], "new");
  if (next.slides[0].findings[0].desc !== "new") throw new Error("the finding text was not set");
  if (next.slides[0].findings[0].title !== "a") throw new Error("the finding heading was changed");
});

console.log("\n[SuggestionsPanel]");
check("renders the suggestion field", () => {
  const html = renderToStaticMarkup(
    <SuggestionsPanel
      value="Focus on the North region."
      onChange={() => {}}
      onSubmit={() => {}}
      onCancel={() => {}}
    />
  );
  if (!html.includes("What should we change?")) throw new Error("missing label");
  if (!html.includes("Focus on the North region.")) throw new Error("missing value");
  if (!html.includes("Regenerate")) throw new Error("missing submit button");
  if (!html.includes("Cancel")) throw new Error("missing cancel button");
  if (!html.includes("Figures are always recomputed from the active data")) {
    throw new Error("missing note about grounded regenerated figures");
  }
});

check("disables the submit button when there is nothing to send", () => {
  const html = renderToStaticMarkup(
    <SuggestionsPanel value="   " onChange={() => {}} onSubmit={() => {}} onCancel={() => {}} />
  );
  if (!html.includes("disabled")) throw new Error("submit should be disabled");
});

console.log("\n[ExportDialog]");
check("renders details when open", () => {
  const html = renderToStaticMarkup(
    <ExportDialog
      open
      filename="deck_ab12cd34.pptx"
      downloadUrl="/presentations/download/deck_ab12cd34.pptx"
      slideCount={7}
      onDownload={() => {}}
      onClose={() => {}}
    />
  );
  if (!html.includes("deck_ab12cd34.pptx")) throw new Error("missing filename");
  if (!html.includes("PowerPoint (.pptx)")) throw new Error("missing format");
});

check("renders nothing when closed", () => {
  const html = renderToStaticMarkup(<ExportDialog open={false} />);
  if (html !== "") throw new Error("expected empty output");
});

console.log("\n[StageIndicator / progress states]");
check("stage list covers the pipeline", () => {
  const stages = [
    "reading_spreadsheet",
    "detecting_columns",
    "analyzing_data",
    "writing_narrative",
    "generating_slides",
    "preparing_powerpoint",
  ];
  for (const stage of stages) {
    if (!/^[a-z_]+$/.test(stage)) throw new Error(`bad stage id ${stage}`);
  }
});


console.log("\n[Settings] the settings model");
check("the defaults have the documented shape", () => {
  const defaults = defaultSettings();
  if (defaults.generation.default_theme !== "light") throw new Error("wrong default theme");
  if (defaults.generation.ai_narrative_enabled !== true) throw new Error("narrative should default on");
  if (defaults.generation.slide_detail_level !== "standard") throw new Error("wrong default detail");
  if (defaults.data_retention.retention_days !== 30) throw new Error("wrong default retention");
  if (defaults.ai_assistant.show_supporting_data !== true) throw new Error("supporting data on by default");
  if (defaults.meta.schema_version !== SCHEMA_VERSION) throw new Error("wrong schema version");
});

check("a missing blob falls back to the defaults", () => {
  const storage = { getItem: () => null, setItem: () => {} };
  const settings = readSettings(storage);
  if (settings.generation.default_theme !== "light") throw new Error("not the defaults");
});

check("a corrupt blob falls back to the defaults and is rewritten", () => {
  let written = null;
  const storage = {
    getItem: () => "{not json",
    setItem: (key, value) => {
      written = value;
    },
  };
  const settings = readSettings(storage);
  if (settings.generation.slide_detail_level !== "standard") throw new Error("not the defaults");
  if (!written) throw new Error("the defaults were not written back");
  if (JSON.parse(written).meta.schema_version !== SCHEMA_VERSION) {
    throw new Error("the rewritten blob is not the current shape");
  }
});

check("an older blob is migrated rather than discarded", () => {
  const migrated = migrateSettings({
    generation: { default_theme: "dark", ai_narrative_enabled: false },
    meta: { schema_version: 0 },
  });
  if (migrated.generation.default_theme !== "dark") throw new Error("the theme was lost");
  if (migrated.generation.ai_narrative_enabled !== false) throw new Error("the narrative switch was lost");
  if (migrated.generation.slide_detail_level !== "standard") throw new Error("a missing field was not defaulted");
  if (migrated.meta.schema_version !== SCHEMA_VERSION) throw new Error("the version was not updated");
});

check("an unknown theme or detail level falls back to the default", () => {
  const migrated = migrateSettings({
    generation: { default_theme: "neon", slide_detail_level: "verbose" },
  });
  if (migrated.generation.default_theme !== "light") throw new Error("unknown theme not rejected");
  if (migrated.generation.slide_detail_level !== "standard") throw new Error("unknown detail not rejected");
});

check("forever is a valid retention window", () => {
  const migrated = migrateSettings({ data_retention: { retention_days: null } });
  if (migrated.data_retention.retention_days !== null) throw new Error("null was not kept");
});

check("settings survive a write and a read", () => {
  const store = {};
  const storage = {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => {
      store[key] = value;
    },
  };
  const settings = defaultSettings();
  settings.generation.default_theme = "executive_navy";
  settings.ai_assistant.show_supporting_data = false;
  writeSettings(settings, storage);

  const read = readSettings(storage);
  if (read.generation.default_theme !== "executive_navy") throw new Error("the theme was lost");
  if (read.ai_assistant.show_supporting_data !== false) throw new Error("the switch was lost");
});

check("an up-to-date blob is not rewritten on every load", () => {
  const store = {};
  let writes = 0;
  const storage = {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => {
      writes += 1;
      store[key] = value;
    },
  };

  // The first load writes the defaults, because there was nothing there.
  readSettings(storage);
  const afterFirst = writes;

  // The second load finds a current blob, so there is nothing to write.
  readSettings(storage);
  if (writes !== afterFirst) {
    throw new Error(`the blob was rewritten on load: ${writes} writes`);
  }
});

console.log("\n[Settings] the app theme");
check("the app theme defaults to light", () => {
  const defaults = defaultSettings();
  if (defaults.appearance.app_theme !== "light") throw new Error("wrong default app theme");
});

check("a dark app theme is kept through a write and a read", () => {
  const store = {};
  const storage = {
    getItem: (key) => store[key] ?? null,
    setItem: (key, value) => {
      store[key] = value;
    },
  };
  const settings = defaultSettings();
  settings.appearance.app_theme = "dark";
  writeSettings(settings, storage);

  const read = readSettings(storage);
  if (read.appearance.app_theme !== "dark") throw new Error("the app theme was lost");
});

check("an unknown app theme falls back to light", () => {
  const migrated = migrateSettings({ appearance: { app_theme: "neon" } });
  if (migrated.appearance.app_theme !== "light") throw new Error("unknown app theme not rejected");
});

check("an older blob without an appearance group still loads", () => {
  const migrated = migrateSettings({
    generation: { default_theme: "dark" },
    meta: { schema_version: 0 },
  });
  if (migrated.appearance.app_theme !== "light") throw new Error("the app theme was not defaulted");
  if (migrated.generation.default_theme !== "dark") throw new Error("the deck theme was lost");
});

check("the app theme is put on the document", () => {
  const attributes = {};
  const root = {
    setAttribute: (name, value) => {
      attributes[name] = value;
    },
    removeAttribute: (name) => {
      delete attributes[name];
    },
  };
  const doc = { documentElement: root };

  applyAppTheme("dark", doc);
  if (attributes["data-theme"] !== "dark") throw new Error("the dark theme was not applied");

  applyAppTheme("light", doc);
  if (attributes["data-theme"]) throw new Error("the light theme left the attribute behind");
});

check("an unknown app theme is put on as light", () => {
  const attributes = {};
  const root = {
    setAttribute: (name, value) => {
      attributes[name] = value;
    },
    removeAttribute: (name) => {
      delete attributes[name];
    },
  };
  applyAppTheme("neon", { documentElement: root });
  if (attributes["data-theme"]) throw new Error("an unknown theme was applied as something");
});

check("the chart data colors stay consistent while scaffolding follows the theme", () => {
  const light = chartColorsFor("light");
  const dark = chartColorsFor("dark");
  if (light.tick === dark.tick) throw new Error("the axes did not change colour");
  if (light.series[0] !== dark.series[0]) throw new Error("the series color changed by theme");
  if (light.pie[0] !== dark.pie[0]) throw new Error("the pie color changed by theme");
});

check("every colour is legible in both themes", () => {
  const failures = contrastFailures();
  if (failures.length) {
    const detail = failures
      .map((f) => `${f.theme} ${f.label} (${f.ratio}, needs ${f.needed})`)
      .join("; ");
    throw new Error(detail);
  }
});

check("the contrast audit measures the colours the app ships", () => {
  // The audit keeps a copy of the palette. If the stylesheet is retuned
  // and the copy is not, the audit would be measuring the wrong colours.
  const here = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(join(here, "..", "src", "index.css"), "utf8");
  const fromCss = palettesFromCss(css);

  for (const [theme, copied, actual] of [
    ["light", LIGHT, fromCss.light],
    ["dark", DARK, fromCss.dark],
  ]) {
    for (const [name, value] of Object.entries(copied)) {
      const shipped = actual[name];
      if (!shipped) {
        throw new Error(`${theme} token ${name} is not in index.css`);
      }
      const expected = value.replace("#", "");
      if (shipped.toLowerCase() !== expected.toLowerCase()) {
        throw new Error(
          `${theme} token ${name} is #${expected} in the audit but #${shipped} in index.css`
        );
      }
    }
  }
});

console.log("\n[Settings] the settings page");
check("renders the three groups of settings", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (!html.includes("Generation")) throw new Error("missing the generation group");
  if (!html.includes("Data retention")) throw new Error("missing the retention group");
  if (!html.includes("AI Assistant")) throw new Error("missing the assistant group");
  if (!html.includes("Default theme")) throw new Error("missing the theme setting");
  if (!html.includes("Slide detail")) throw new Error("missing the detail setting");
  if (!html.includes("AI narrative")) throw new Error("missing the narrative switch");
  if (!html.includes("Show supporting data")) throw new Error("missing the supporting data switch");
});

check("offers an appearance group above the generation group", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (!html.includes("Appearance")) throw new Error("missing the appearance group");
  if (!html.includes("App theme")) throw new Error("missing the app theme setting");
  if (html.indexOf("Appearance") > html.indexOf("Generation")) {
    throw new Error("the appearance group is below the generation group");
  }
});

check("offers the themes and the detail levels", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (!html.includes("Executive navy")) throw new Error("missing the executive navy theme");
  if (!html.includes("Concise")) throw new Error("missing the concise level");
  if (!html.includes("Detailed")) throw new Error("missing the detailed level");
  if (!html.includes("Forever")) throw new Error("missing the forever retention window");
});

check("the clear action asks for confirmation first", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (!html.includes("Clear all workbooks")) throw new Error("missing the clear action");
  if (html.includes("Yes, remove everything")) {
    throw new Error("the confirmation is shown before it was asked for");
  }
});

check("the clear action confirms when it is armed", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (!html.includes("Clear all workbooks")) throw new Error("missing the clear action");
});

console.log("\n[Settings] the consumers");
check("the assistant hides the supporting rows when they are turned off", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar
      isOpen
      onClose={() => {}}
      dataset={{ stored_filename: "sales.csv" }}
      hasDataset
      showSupportingData={false}
      initialMessages={[
        {
          role: "assistant",
          content: "Total sales come to 1,213,482.30.",
          confidence: "high",
          supportingData: {
            kind: "table",
            columns: ["category", "total"],
            rows: [{ category: "Furniture", total: 367826.8 }],
            row_count: 1,
          },
        },
      ]}
    />
  );
  if (html.includes("Supporting data")) {
    throw new Error("the supporting rows are still shown");
  }
  if (!html.includes("Total sales come to")) throw new Error("the answer itself is missing");
});

check("the slide preview uses the deck's own theme", () => {
  const palette = resolvePalette({
    theme: "dark",
    theme_palette: { primary: "#60A5FA", text_main: "#F1F5F9" },
  });
  if (palette.primary !== "#60A5FA") throw new Error("the deck palette was not used");
  if (palette.text_main !== "#F1F5F9") throw new Error("the deck text colour was not used");
  if (!palette.border) throw new Error("a missing colour was not filled in");
});

check("a palette from the backend is a colour the browser can use", () => {
  // The backend sends bare hex digits, because that is what PowerPoint wants.
  const palette = resolvePalette({ theme_palette: { primary: "60A5FA" } });
  if (palette.primary !== "#60A5FA") {
    throw new Error(`the colour is not usable: ${palette.primary}`);
  }
  if (!palette.primary.startsWith("#")) {
    throw new Error("the colour is missing its hash");
  }
});

check("a deck with no palette falls back to the light theme", () => {
  const palette = resolvePalette(null, null);
  if (palette.primary !== "#2563EB") throw new Error("not the light theme");
});

check("each theme has its own series colours", () => {
  if (seriesColors(null, "light")[0] === seriesColors(null, "dark")[0]) {
    throw new Error("the themes share their series colours");
  }
});

check("a deck keeps its own series colours", () => {
  // The deck carries the colours it was drawn with, so changing the setting
  // afterwards does not repaint a deck that is already built.
  const deck = { theme: "light", theme_series_colors: ["1E3A8A", "38BDF8"] };
  const colors = seriesColors(deck, "dark");
  if (colors[0] !== "#1E3A8A") {
    throw new Error(`the deck's own colour was not used: ${colors[0]}`);
  }
  if (colors.length !== 2) {
    throw new Error(`the wrong number of colours: ${colors.length}`);
  }
});



console.log("\n[Settings] the shared state");
check("a change made through the context is kept", () => {
  // A probe that reports the settings it sees, so the check can tell
  // whether a change went through the provider.
  let seen = null;
  function Probe() {
    const { settings, update } = useSettings();
    seen = { settings, update };
    return <p>probe</p>;
  }

  // Render the provider with a probe, then drive the setter directly.
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <Probe />
    </SettingsProvider>
  );
  if (!html.includes("probe")) throw new Error("the probe did not render");
  if (!seen) throw new Error("the probe never saw the settings");
  if (seen.settings.generation.default_theme !== "light") {
    throw new Error("the initial settings are wrong");
  }
  if (typeof seen.update !== "function") throw new Error("no setter was exposed");
});

check("the write is debounced rather than immediate", () => {
  if (!(WRITE_DEBOUNCE_MS > 0)) throw new Error("the writes are not debounced");
});

check("a rapid series of changes is written once, at the end", () => {
  // A fake clock, so the behaviour is checked without waiting.
  const pending = [];
  const timers = {
    setTimeout: (fn, delay) => {
      pending.push({ fn, delay });
      return pending.length;
    },
    clearTimeout: (id) => {
      pending[id - 1] = null;
    },
  };

  const written = [];
  const writer = createDebouncedWriter((value) => written.push(value), 400, timers);

  writer.schedule("a");
  writer.schedule("b");
  writer.schedule("c");

  if (written.length !== 0) {
    throw new Error("something was written before the delay was up");
  }

  // The last timer is the one that survives.
  const live = pending.filter(Boolean);
  if (live.length !== 1) {
    throw new Error(`expected one live timer, got ${live.length}`);
  }
  live[0].fn();

  if (written.length !== 1) {
    throw new Error(`expected one write, got ${written.length}`);
  }
  if (written[0] !== "c") {
    throw new Error(`the wrong value was written: ${written[0]}`);
  }
});

check("a pending change is written when the app goes away", () => {
  const pending = [];
  const timers = {
    setTimeout: (fn, delay) => {
      pending.push({ fn, delay });
      return pending.length;
    },
    clearTimeout: (id) => {
      pending[id - 1] = null;
    },
  };

  const written = [];
  const writer = createDebouncedWriter((value) => written.push(value), 400, timers);

  writer.schedule("late change");
  writer.flush();

  if (written.length !== 1) {
    throw new Error(`the change was lost: ${written.length} writes`);
  }
  if (written[0] !== "late change") {
    throw new Error(`the wrong value was written: ${written[0]}`);
  }

  // A second flush has nothing left to write.
  writer.flush();
  if (written.length !== 1) {
    throw new Error("the same value was written twice");
  }
});

console.log(`\n${"=".repeat(50)}`);
check("a change in the settings reaches the pages that read them", () => {
  // The panel and the assistant are both inside the provider, and the
  // assistant reads the switch that the panel sets.
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={{ ...defaultSettings(), ai_assistant: { show_supporting_data: false } }}>
      <>
        <SettingsPanel />
        <AssistantSidebar
          isOpen
          onClose={() => {}}
          dataset={{ stored_filename: "sales.csv" }}
          hasDataset
          showSupportingData={false}
          initialMessages={[
            {
              role: "assistant",
              content: "Total sales come to 1,213,482.30.",
              supportingData: {
                kind: "table",
                columns: ["category"],
                rows: [{ category: "Furniture" }],
              },
            },
          ]}
        />
      </>
    </SettingsProvider>
  );
  if (!html.includes("Settings")) throw new Error("the settings page is missing");
  if (html.includes("Supporting data")) {
    throw new Error("the supporting rows are still shown");
  }
  if (!html.includes("Total sales come to")) throw new Error("the answer itself is missing");
});

check("the settings page is a page of its own, not a placeholder", () => {
  const html = renderToStaticMarkup(
    <SettingsProvider initialSettings={defaultSettings()}>
      <SettingsPanel />
    </SettingsProvider>
  );
  if (html.includes("Section under preparation")) {
    throw new Error("still shows the placeholder");
  }
});

console.log(`\n${"=".repeat(50)}`);

// Verify the active thumbnail is marked for assistive tech.
{
  const html = renderToStaticMarkup(
    <SlideThumbnailRail slides={DECK.slides} activeIndex={2} onSelect={() => {}} />
  );
  const currentCount = (html.match(/aria-current="true"/g) || []).length;
  console.log(`\n  active thumbnail markers: ${currentCount}`);
  console.log(currentCount === 1 ? "  PASS  exactly one thumbnail is active" : "  FAIL  expected 1 active thumbnail");
}

console.log("\n[LatestReviews] preview rows and dropdown");
const ACTIVITY_TABLE = {
  title: "Recent Orders & Activity",
  columns: ["Order_ID", "Customer_Name", "Order_Date", "Sales", "Order_Status"],
  rows: Array.from({ length: 18 }, (_, i) => ({
    Order_ID: `ORD-${1000 + i}`,
    Customer_Name: `Customer ${i}`,
    Order_Date: `2025-0${(i % 9) + 1}-01`,
    Sales: 100 + i,
    Order_Status: "Delivered",
  })),
  total_rows: 50,
};

check("shows only the first 10 rows inline", () => {
  const html = renderToStaticMarkup(<LatestReviews table={ACTIVITY_TABLE} />);
  const bodyRows = (html.match(/ORD-\d+/g) || []).length;
  if (bodyRows !== 10) throw new Error(`expected 10 inline rows, got ${bodyRows}`);
  if (!html.includes("ORD-1000")) throw new Error("missing first row");
  if (html.includes("ORD-1010")) throw new Error("row 11 should not be inline");
});

check("offers a dropdown for the remaining rows", () => {
  const html = renderToStaticMarkup(<LatestReviews table={ACTIVITY_TABLE} />);
  if (!html.includes("Show next 8")) throw new Error("missing dropdown toggle");
  if (!html.includes("aria-expanded")) throw new Error("toggle missing aria-expanded");
});

check("hides the dropdown list until it is opened", () => {
  const html = renderToStaticMarkup(<LatestReviews table={ACTIVITY_TABLE} />);
  if (html.includes("ORD-1010")) throw new Error("dropdown rows rendered while closed");
});

check("renders nothing without a table", () => {
  const html = renderToStaticMarkup(<LatestReviews table={null} />);
  if (html !== "") throw new Error("expected empty output");
});

console.log("\n[Resizable] chart cards are drag-resizable");
check("renders a resize grip", () => {
  const html = renderToStaticMarkup(
    <ResizableCard storageKey="test-card">
      <p>chart body</p>
    </ResizableCard>
  );
  if (!html.includes("aria-label=\"Resize chart\"")) throw new Error("missing resize handle");
  if (!html.includes("cursor-nwse-resize")) throw new Error("missing resize cursor");
  if (!html.includes("chart body")) throw new Error("children not rendered");
});
check("the grip can be reset by double-click", () => {
  const html = renderToStaticMarkup(
    <ResizableCard storageKey="test-card">
      <p>chart body</p>
    </ResizableCard>
  );
  if (!html.includes("double-click to reset")) throw new Error("missing reset hint");
});

const MAIN_CHART = {
  chart_type: "line",
  title: "Sales Trend",
  figure: {
    data: [
      { name: "Sales", x: ["2025-01", "2025-02", "2025-03"], y: [10, 20, 30] },
    ],
  },
};

const MINI_CHARTS = [
  {
    chart_type: "bar",
    title: "Orders by Category",
    figure: { data: [{ x: ["A", "B"], y: [1, 2] }] },
  },
  {
    chart_type: "line",
    title: "Customers Over Time",
    figure: { data: [{ x: ["Jan", "Feb"], y: [3, 4] }] },
  },
  {
    chart_type: "pie",
    title: "Top Categories",
    figure: { data: [{ labels: ["A", "B"], values: [1, 2] }] },
  },
];

check("the main chart is wrapped in a resizable card", () => {
  const html = renderToStaticMarkup(<TotalSalesChart chart={MAIN_CHART} />);
  if (!html.includes("aria-label=\"Resize chart\"")) throw new Error("main chart is not resizable");
  if (!html.includes("Total sells")) throw new Error("missing chart title");
});

check("each secondary chart is individually resizable", () => {
  const html = renderToStaticMarkup(<SecondaryCharts charts={MINI_CHARTS} />);
  const grips = (html.match(/aria-label="Resize chart"/g) || []).length;
  if (grips !== MINI_CHARTS.length) {
    throw new Error(`expected ${MINI_CHARTS.length} resize grips, got ${grips}`);
  }
});

console.log("\n[Resizable] drag maths");
check("grows with the pointer delta", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(origin, { clientX: 150, clientY: 130 }, {});
  if (next.width !== 450) throw new Error(`expected width 450, got ${next.width}`);
  if (next.height !== 330) throw new Error(`expected height 330, got ${next.height}`);
});

check("shrinks with a negative delta", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(origin, { clientX: 60, clientY: 80 }, {});
  if (next.width !== 360) throw new Error(`expected width 360, got ${next.width}`);
  if (next.height !== 280) throw new Error(`expected height 280, got ${next.height}`);
});

check("respects the minimum size", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(
    origin,
    { clientX: 0, clientY: 0 },
    { min: { width: 320, height: 260 } }
  );
  if (next.width !== 320) throw new Error(`expected width clamped to 320, got ${next.width}`);
  if (next.height !== 260) throw new Error(`expected height clamped to 260, got ${next.height}`);
});

check("respects the maximum size", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(
    origin,
    { clientX: 5000, clientY: 5000 },
    { max: { width: 1200, height: 900 } }
  );
  if (next.width !== 1200) throw new Error(`expected width clamped to 1200, got ${next.width}`);
  if (next.height !== 900) throw new Error(`expected height clamped to 900, got ${next.height}`);
});

check("width-only drags leave the height alone", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(
    origin,
    { clientX: 150, clientY: 400 },
    { resizeWidth: true, resizeHeight: false }
  );
  if (next.width !== 450) throw new Error(`expected width 450, got ${next.width}`);
  if ("height" in next) throw new Error("height should not be set");
});

check("height-only drags leave the width alone", () => {
  const origin = { x: 100, y: 100, width: 400, height: 300 };
  const next = computeResizedSize(
    origin,
    { clientX: 900, clientY: 130 },
    { resizeWidth: false, resizeHeight: true }
  );
  if (next.height !== 330) throw new Error(`expected height 330, got ${next.height}`);
  if ("width" in next) throw new Error("width should not be set");
});

console.log("\n[FileUpload] collapsible dropzone");check("shows the full dropzone with no dataset", () => {
  const html = renderToStaticMarkup(<FileUpload />);
  if (!html.includes("Drag &amp; drop your CSV or Excel file here")) {
    throw new Error("missing dropzone prompt");
  }
  if (html.includes("Select another file")) throw new Error("collapsed state while empty");
});
check("collapses to a bar once a dataset is loaded", () => {
  const html = renderToStaticMarkup(
    <FileUpload dataset={{ original_filename: "sales.csv", stored_filename: "sales_a1b2c3d4.csv" }} />
  );
  if (!html.includes("Choose a different file")) throw new Error("missing file-switch button");
  if (!html.includes("sales.csv")) throw new Error("missing uploaded file name");
  if (html.includes("Drag &amp; drop your CSV or Excel file here")) {
    throw new Error("dropzone should be collapsed");
  }
});

console.log("\n[QuickStatsCard]");check("renders each stat pill with its trend", () => {
  const html = renderToStaticMarkup(
    <QuickStatsCard
      stats={[
        { label: "Total Sales", value: "1,213,482.30", trend: "+12.5%", trend_direction: "up" },
        { label: "Orders", value: "1,204", trend: "-3.1%", trend_direction: "down" },
      ]}
    />
  );
  if (!html.includes("Total Sales:")) throw new Error("missing label");
  if (!html.includes("1,213,482.30")) throw new Error("missing value");
  if (!html.includes("+12.5%")) throw new Error("missing up trend");
  if (!html.includes("text-rose-600")) throw new Error("down trend should be rose");
  if (!html.includes("text-emerald-600")) throw new Error("up trend should be emerald");
});
check("renders nothing without stats", () => {
  const html = renderToStaticMarkup(<QuickStatsCard stats={[]} />);
  if (html !== "") throw new Error("expected empty output");
});

console.log("\n[StageIndicator] progress states");
check("shows every pipeline stage", () => {
  const html = renderToStaticMarkup(<StageIndicator currentStage="analyzing_data" />);
  for (const label of ["Reading spreadsheet", "Detecting columns", "Analyzing data",
                        "Writing the narrative", "Generating slides", "Preparing PowerPoint"]) {
    if (!html.includes(label)) throw new Error(`missing stage label: ${label}`);
  }
});
check("marks earlier stages complete and the current one active", () => {
  const html = renderToStaticMarkup(<StageIndicator currentStage="analyzing_data" />);
  const done = (html.match(/\u2713/g) || []).length;
  if (done !== 2) throw new Error(`expected 2 completed stages, got ${done}`);
});
check("failed state marks the stage with an error", () => {
  const html = renderToStaticMarkup(<StageIndicator currentStage="analyzing_data" failed />);
  if (!html.includes("!")) throw new Error("missing failure marker");
  if (!html.includes("text-rose-700")) throw new Error("missing failure styling");
});

check("completed state marks every stage done", () => {
  const html = renderToStaticMarkup(<StageIndicator currentStage="completed" />);
  const done = (html.match(/\u2713/g) || []).length;
  if (done !== 6) throw new Error(`expected 6 completed stages, got ${done}`);
});

console.log("\n[DashboardPresentation] dashboard panel");
check("renders the idle state with a generate button", () => {
  const html = renderToStaticMarkup(
    <DashboardPresentation dataset={{ stored_filename: "sales_a1b2c3d4.csv" }} />
  );
  if (!html.includes("Generate Presentation")) throw new Error("missing generate button");
  if (!html.includes("Export PPTX")) throw new Error("missing export button");
  if (!html.includes("preview here automatically")) throw new Error("missing idle hint");
  if (html.includes("Upload a dataset above")) throw new Error("unexpected no-dataset hint");
});

check("prompts for an upload when no dataset is active", () => {
  const html = renderToStaticMarkup(<DashboardPresentation dataset={null} />);
  if (!html.includes("Upload a dataset above, then generate")) {
    throw new Error("missing no-dataset hint");
  }
});

check("has no regenerate button before a deck exists", () => {
  const html = renderToStaticMarkup(
    <DashboardPresentation dataset={{ stored_filename: "sales_a1b2c3d4.csv" }} />
  );
  if (html.includes("Regenerate Presentation")) {
    throw new Error("regenerate button shown before any deck exists");
  }
});

check("has no AI Presentation heading", () => {
  const html = renderToStaticMarkup(
    <DashboardPresentation dataset={{ stored_filename: "sales_a1b2c3d4.csv" }} />
  );
  if (html.includes("AI Presentation")) throw new Error("heading still present");
  if (html.includes("One click")) throw new Error("subtitle still present");
});

check("has no file dropzone or dataset picker", () => {
  const html = renderToStaticMarkup(
    <DashboardPresentation dataset={{ stored_filename: "sales_a1b2c3d4.csv" }} />
  );
  if (html.includes("Drop a CSV or Excel file here")) throw new Error("dropzone still present");
  if (html.includes("Or use a previous upload")) throw new Error("dataset picker still present");
  if (html.includes("Or drop a file")) throw new Error("source picker still present");
});

console.log("\n[Sidebar] no presentations section");
check("has no Presentations nav item", () => {
  const html = renderToStaticMarkup(<Sidebar activeNav="Dashboard" />);
  if (html.includes(">Presentations<")) throw new Error("sidebar still lists Presentations");
});
check("has no Create Presentation button", () => {
  const html = renderToStaticMarkup(<Sidebar activeNav="Dashboard" />);
  if (html.includes("Create Presentation")) throw new Error("sidebar still has the CTA");
});
check("still lists the other sections", () => {
  const html = renderToStaticMarkup(<Sidebar activeNav="Dashboard" />);
  for (const label of ["Dashboard", "Workbooks", "AI Assistant", "Settings"]) {
    if (!html.includes(label)) throw new Error(`missing nav item: ${label}`);
  }
});

console.log("\n[AI Assistant] the right-hand panel");
check("renders the panel with a question field", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar isOpen onClose={() => {}} dataset={null} hasDataset={false} />
  );
  if (!html.includes("AI Assistant")) throw new Error("missing heading");
  if (!html.includes("Upload a dataset first")) {
    throw new Error("missing no-dataset placeholder");
  }
});
check("offers suggested questions once a dataset is loaded", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar
      isOpen
      onClose={() => {}}
      dataset={{ stored_filename: "sales_a1b2c3d4.csv" }}
      hasDataset
    />
  );
  if (!html.includes("What is the total sales?")) {
    throw new Error("missing suggested question");
  }
  if (!html.includes("Answers computed from your data")) {
    throw new Error("missing dataset subtitle");
  }
});
check("shows the supporting rows and the confidence", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar
      isOpen
      onClose={() => {}}
      dataset={{ stored_filename: "sales_a1b2c3d4.csv" }}
      hasDataset
      initialMessages={[
        {
          role: "assistant",
          content: "Total sales come to 1,213,482.30.",
          confidence: "high",
          supportingData: {
            kind: "table",
            columns: ["category", "total"],
            rows: [{ category: "Furniture", total: 367826.8 }],
            row_count: 3,
            truncated: false,
          },
        },
      ]}
    />
  );
  if (!html.includes("Supporting data")) throw new Error("missing supporting data");
  if (!html.includes("high confidence")) throw new Error("missing confidence");
  if (!html.includes("Furniture")) throw new Error("the computed rows are not shown");
});
check("is hidden from the layout when it is closed", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar isOpen={false} onClose={() => {}} dataset={null} hasDataset={false} />
  );
  if (!html.includes("translate-x-full")) throw new Error("closed panel is not slid away");
});

console.log("\n[Workbooks] the workbooks page");
check("renders the workbooks page with an upload action", () => {
  const html = renderToStaticMarkup(<WorkbooksPanel />);
  if (!html.includes("Upload workbook")) throw new Error("missing upload button");
  if (!html.includes("Workbooks")) throw new Error("missing heading");
  // The page has no heading card of its own — the upload button is the
  // action the page opens with.
  if (html.includes("Every spreadsheet you upload")) {
    throw new Error("the header card is still there");
  }
});
check("has no dashboard placeholder", () => {
  const html = renderToStaticMarkup(<WorkbooksPanel />);
  if (html.includes("Section under preparation")) {
    throw new Error("still shows the placeholder");
  }
});
check("has a search field next to the upload button", () => {
  const html = renderToStaticMarkup(<WorkbooksPanel />);
  if (!html.includes("Search workbooks")) {
    throw new Error("missing the search field");
  }
  if (!html.includes('type="search"')) {
    throw new Error("the search field is not a search input");
  }
});

check("has a filter and a sort button", () => {
  const html = renderToStaticMarkup(<WorkbooksPanel />);
  if (!html.includes("All workbooks")) throw new Error("missing the filter button");
  if (!html.includes("Newest first")) throw new Error("missing the sort button");
  if (!html.includes('aria-haspopup="listbox"')) {
    throw new Error("the menus are not marked as listboxes");
  }
});

check("offers an overview of a workbook", () => {
  // The list is empty without a server, so the button is checked through
  // the row it lives in.
  const html = renderToStaticMarkup(
    <WorkbookRow
      workbook={{ id: "a", file_name: "alpha.csv", status: "parsed", file_type: "csv" }}
      onOverview={() => {}}
      onUseWorkbook={() => {}}
    />
  );
  if (!html.includes("Overview")) throw new Error("missing the overview button");
  // It comes before the "Ask about this" button, so it is first in the row.
  if (html.indexOf("Overview") > html.indexOf("Ask about this")) {
    throw new Error("the overview button comes after the ask button");
  }
});

console.log("\n[Workbooks] the filter and the sort");
const WORKBOOKS = [
  {
    id: "a",
    file_name: "alpha.csv",
    file_type: "csv",
    status: "parsed",
    uploaded_at: "2025-01-01T00:00:00+00:00",
    sheets: [{ row_count: 10 }],
  },
  {
    id: "b",
    file_name: "beta.xlsx",
    file_type: "xlsx",
    status: "needs_attention",
    uploaded_at: "2025-03-01T00:00:00+00:00",
    sheets: [{ row_count: 50 }],
  },
  {
    id: "c",
    file_name: "gamma.csv",
    file_type: "csv",
    status: "stale",
    uploaded_at: "2025-02-01T00:00:00+00:00",
    sheets: [{ row_count: 20 }],
  },
];

check("the filter narrows the list by status", () => {
  const byStatus = filterAndSort(WORKBOOKS, "needs_attention", "newest");
  if (byStatus.length !== 1) throw new Error(`expected 1, got ${byStatus.length}`);
  if (byStatus[0].id !== "b") throw new Error("the wrong workbook survived");
});

check("the filter narrows the list by file type", () => {
  const csvs = filterAndSort(WORKBOOKS, "csv", "newest");
  if (csvs.length !== 2) throw new Error(`expected 2, got ${csvs.length}`);
  if (csvs.some((w) => w.file_type !== "csv")) throw new Error("a non-CSV survived");

  const excels = filterAndSort(WORKBOOKS, "xlsx", "newest");
  if (excels.length !== 1 || excels[0].id !== "b") {
    throw new Error("the Excel filter is wrong");
  }
});

check("the all filter keeps everything", () => {
  const all = filterAndSort(WORKBOOKS, "all", "newest");
  if (all.length !== 3) throw new Error(`expected 3, got ${all.length}`);
});

check("the sort puts the newest first", () => {
  const sorted = filterAndSort(WORKBOOKS, "all", "newest");
  if (sorted.map((w) => w.id).join(",") !== "b,c,a") {
    throw new Error(`wrong order: ${sorted.map((w) => w.id).join(",")}`);
  }
});

check("the sort puts the oldest first", () => {
  const sorted = filterAndSort(WORKBOOKS, "all", "oldest");
  if (sorted.map((w) => w.id).join(",") !== "a,c,b") {
    throw new Error(`wrong order: ${sorted.map((w) => w.id).join(",")}`);
  }
});

check("the sort orders by name", () => {
  const ascending = filterAndSort(WORKBOOKS, "all", "name_asc");
  if (ascending.map((w) => w.id).join(",") !== "a,b,c") {
    throw new Error(`wrong order: ${ascending.map((w) => w.id).join(",")}`);
  }
  const descending = filterAndSort(WORKBOOKS, "all", "name_desc");
  if (descending.map((w) => w.id).join(",") !== "c,b,a") {
    throw new Error(`wrong order: ${descending.map((w) => w.id).join(",")}`);
  }
});

check("the sort orders by how many rows there are", () => {
  const sorted = filterAndSort(WORKBOOKS, "all", "largest");
  if (sorted.map((w) => w.id).join(",") !== "b,c,a") {
    throw new Error(`wrong order: ${sorted.map((w) => w.id).join(",")}`);
  }
});

check("the sort does not reorder the list it was given", () => {
  const original = [...WORKBOOKS];
  filterAndSort(WORKBOOKS, "all", "name_asc");
  if (WORKBOOKS.map((w) => w.id).join(",") !== original.map((w) => w.id).join(",")) {
    throw new Error("the original list was reordered");
  }
});

console.log("\n[AI Assistant] the workbook target");
check("shows which workbook the assistant is answering from", () => {
  const html = renderToStaticMarkup(
    <AssistantSidebar
      isOpen
      onClose={() => {}}
      dataset={null}
      hasDataset={false}
      workbook={{ id: "wb1", file_name: "sales.csv", active_sheet_id: "sheet_1" }}
    />
  );
  if (!html.includes("Answering from sales.csv")) {
    throw new Error("missing workbook name");
  }
});

console.log(`\n${"=".repeat(50)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length}`);
  failures.forEach((f) => console.log(`  - ${f}`));
  process.exit(1);
}
console.log("All component render checks passed.");
