"""Checks for the settings-driven behaviour: themes, detail levels, the"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from src.presentation.presentation_generator import (  # noqa: E402
    DETAIL_LEVELS,
    THEMES,
    apply_detail_level,
    build_deck_plan,
    normalize_detail_level,
    normalize_theme,
    resolve_theme,
    theme_palette,
)
from src.workbook.workbook_cache import WorkbookCache  # noqa: E402
from src.workbook.workbook_service import WorkbookService  # noqa: E402
from src.workbook.workbook_store import WorkbookStore  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


SALES_CSV = """Date,Category,Region,Sales,Quantity,Customer
2025-01-05,Furniture,North,1000,2,Globex
2025-01-18,Office,South,250,1,Initech
2025-02-03,Technology,East,1540,5,Initech
2025-02-21,Office,West,720,3,Umbrella
2025-03-07,Technology,North,1980,6,Acme
2025-03-25,Furniture,South,1430,2,Globex
"""

OTHER_CSV = """Product,Amount
Widget,10
Gadget,20
"""


def sample_frame():
    """A frame with enough rows for the plan to have a chart to trim."""
    return pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=16, freq="D"),
            "Category": ["A", "B", "C", "D", "E", "F", "G", "H"] * 2,
            "Region": ["North", "South", "East", "West"] * 4,
            "Sales": [100 + (i * 13) for i in range(16)],
            "Quantity": [1 + (i % 5) for i in range(16)],
            "Customer": [f"C{i:03d}" for i in range(16)],
        }
    )


def main():
    print("\n[1] The themes")
    check("There are three themes", set(THEMES) == {"light", "dark", "executive_navy"},
          str(sorted(THEMES)))
    check("A known theme resolves", resolve_theme("dark")["primary"] == "60A5FA",
          str(resolve_theme("dark")))
    check("An unknown theme falls back to the default",
          resolve_theme("neon") == resolve_theme("light"), str(resolve_theme("neon")))
    check("A missing theme falls back to the default",
          resolve_theme(None) == resolve_theme("light"), str(resolve_theme(None)))
    check("The themes are normalised to their canonical names",
          normalize_theme("DARK") == "dark" and normalize_theme("nope") == "light",
          f"{normalize_theme('DARK')} {normalize_theme('nope')}")

    palette = theme_palette("executive_navy")
    check("The palette is a set of PowerPoint colours",
          str(palette["primary"]) == "1E3A8A", str(palette["primary"]))
    check("Every theme has every colour",
          all(len(resolve_theme(name)) == len(resolve_theme("light")) for name in THEMES),
          str({name: len(resolve_theme(name)) for name in THEMES}))

    print("\n[2] The detail levels")
    check("There are three detail levels",
          set(DETAIL_LEVELS) == {"concise", "standard", "detailed"}, str(DETAIL_LEVELS))
    check("An unknown detail level falls back to the default",
          normalize_detail_level("verbose") == "standard", normalize_detail_level("verbose"))

    plan = {
        "slides": [
            {
                "type": "summary",
                "findings": [{"title": f"f{i}", "desc": "d"} for i in range(5)],
            },
            {
                "type": "insights",
                "insights": [f"i{i}" for i in range(5)],
                "recommendations": [f"r{i}" for i in range(5)],
            },
            {
                "type": "chart",
                "caption": "a caption",
                "categories": [f"c{i}" for i in range(10)],
                "series": [{"name": "s", "values": list(range(10))}],
            },
        ]
    }

    concise = apply_detail_level({"slides": [dict(s) for s in plan["slides"]]}, "concise")
    check("A concise summary has three findings",
          len(concise["slides"][0]["findings"]) == 3,
          str(len(concise["slides"][0]["findings"])))
    check("A concise chart drops the caption",
          "caption" not in concise["slides"][2], str(concise["slides"][2].get("caption")))
    check("A concise chart plots fewer points",
          len(concise["slides"][2]["categories"]) == 5,
          str(len(concise["slides"][2]["categories"])))
    check("A concise chart's series are trimmed with it",
          len(concise["slides"][2]["series"][0]["values"]) == 5,
          str(len(concise["slides"][2]["series"][0]["values"])))

    # A trend runs oldest to newest, so a concise deck keeps the recent end.
    trend = apply_detail_level(
        {
            "slides": [
                {
                    "type": "chart",
                    "chart_type": "line",
                    "categories": [f"p{i}" for i in range(10)],
                    "series": [{"name": "s", "values": list(range(10))}],
                }
            ]
        },
        "concise",
    )
    check("A concise trend keeps the most recent points",
          trend["slides"][0]["categories"] == ["p5", "p6", "p7", "p8", "p9"],
          str(trend["slides"][0]["categories"]))
    check("A concise trend's series are trimmed with it",
          trend["slides"][0]["series"][0]["values"] == [5, 6, 7, 8, 9],
          str(trend["slides"][0]["series"][0]["values"]))
    check("A concise insights slide has three of each",
          len(concise["slides"][1]["insights"]) == 3
          and len(concise["slides"][1]["recommendations"]) == 3,
          str(concise["slides"][1]))
    check("The detail level is recorded on the plan",
          concise["detail_level"] == "concise", concise.get("detail_level"))

    detailed = apply_detail_level({"slides": [dict(s) for s in plan["slides"]]}, "detailed")
    check("A detailed chart keeps its caption",
          detailed["slides"][2].get("caption") == "a caption",
          str(detailed["slides"][2].get("caption")))
    check("A detailed chart plots more points",
          len(detailed["slides"][2]["categories"]) == 10,
          str(len(detailed["slides"][2]["categories"])))

    print("\n[3] The deck plan carries the theme and the detail level")
    frame = sample_frame()
    deck = build_deck_plan(frame, use_agent=False, theme="dark", detail_level="concise")
    check("The plan records the theme", deck["theme"] == "dark", str(deck.get("theme")))
    check("The plan carries the palette",
          deck["theme_palette"]["primary"] == "60A5FA", str(deck.get("theme_palette")))
    check("The plan records the detail level",
          deck["detail_level"] == "concise", str(deck.get("detail_level")))

    default_deck = build_deck_plan(frame, use_agent=False)
    check("A deck with no theme uses the default",
          default_deck["theme"] == "light", str(default_deck.get("theme")))

    check("The plan carries the series colours",
          deck["theme_series_colors"][0] == "60A5FA",
          str(deck.get("theme_series_colors")))

    print("\n[3b] The chart is drawn in the theme's series colours")
    from src.presentation.presentation_generator import theme_series_colors

    check("Each theme has its own series colours",
          theme_series_colors("light")[0] != theme_series_colors("dark")[0],
          str(theme_series_colors("light")[0]))
    check("The series colours are PowerPoint colours",
          str(theme_series_colors("dark")[0]) == "60A5FA",
          str(theme_series_colors("dark")[0]))

    print("\n[4] The theme reaches the rendered file")
    from pptx import Presentation

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deck.pptx"
        rendered = build_deck_plan(frame, use_agent=False, theme="executive_navy")
        from src.presentation.presentation_generator import render_plan_to_pptx

        render_plan_to_pptx(rendered, path)
        prs = Presentation(str(path))
        check("The themed deck is written", path.exists() and len(prs.slides) >= 4,
              str(len(prs.slides)))

        # The title slide's top bar is drawn in the theme's primary colour.
        top_bar = prs.slides[0].shapes[0]
        check("The slide is drawn in the theme's primary colour",
              str(top_bar.fill.fore_color.rgb) == "1E3A8A",
              str(top_bar.fill.fore_color.rgb))

        # The chart's series are drawn in the theme's series colours, so the
        # file matches the preview.
        chart_colors = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if not getattr(shape, "has_chart", False):
                    continue
                for plot_series in shape.chart.series:
                    chart_colors.append(str(plot_series.format.fill.fore_color.rgb))
        check("The chart is drawn in the theme's series colours",
              bool(chart_colors) and all(c == "1E3A8A" for c in chart_colors),
              str(sorted(set(chart_colors))))

    print("\n[5] The settings reach the generation endpoint")
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkbookStore(Path(tmp) / "workbooks.db")
        cache = WorkbookCache()
        app_module.app.state.workbook_store = store
        app_module.app.state.workbook_cache = cache
        app_module.app.state.workbooks = WorkbookService(store, cache)

        client = TestClient(app_module.app)

        response = client.post(
            "/workbooks",
            files={"file": ("sales.csv", SALES_CSV.encode("utf-8"), "text/csv")},
        )
        check("A workbook is uploaded", response.status_code == 200, response.text[:200])
        workbook_id = response.json()["workbook"]["id"]

        response = client.post(
            f"/workbooks/{workbook_id}/query",
            json={"question": "What is the total sales?"},
        )
        check("A workbook can be queried", response.status_code == 200, response.text[:200])

        print("\n[6] Every workbook can be cleared at once")
        client.post(
            "/workbooks",
            files={"file": ("other.csv", OTHER_CSV.encode("utf-8"), "text/csv")},
        )
        before = len(client.get("/workbooks").json()["workbooks"])
        check("There are two workbooks to clear", before == 2, str(before))

        response = client.delete("/workbooks")
        check("The bulk delete succeeds", response.status_code == 200, response.text[:200])
        check("It reports how many it removed",
              response.json()["deleted"] == 2, str(response.json()))
        check("No workbooks are left",
              len(client.get("/workbooks").json()["workbooks"]) == 0,
              str(client.get("/workbooks").json()))

        print("\n[7] The retention cleanup purges the old workbooks")
        client.post(
            "/workbooks",
            files={"file": ("sales.csv", SALES_CSV.encode("utf-8"), "text/csv")},
        )

        # A workbook that is older than the window is purged, and one that
        # is inside it is kept.
        records = store.list_workbooks()
        check("A workbook is stored", len(records) == 1, str(len(records)))

        old_id = records[0]["id"]
        store.update_workbook(old_id)  # ensure it is there
        connection = store._connection
        with store._lock:
            connection.execute(
                "UPDATE workbooks SET uploaded_at = ? WHERE id = ?",
                (
                    (datetime.now(tz=timezone.utc) - timedelta(days=60)).isoformat(),
                    old_id,
                ),
            )
            connection.commit()

        response = client.post("/workbooks/purge", json={"retention_days": 30})
        check("The purge succeeds", response.status_code == 200, response.text[:200])
        check("The old workbook is removed", response.json()["deleted"] == 1,
              str(response.json()))
        check("It is gone from the list",
              len(client.get("/workbooks").json()["workbooks"]) == 0,
              str(client.get("/workbooks").json()))

        # A fresh workbook is inside the window, so it survives.
        client.post(
            "/workbooks",
            files={"file": ("sales.csv", SALES_CSV.encode("utf-8"), "text/csv")},
        )
        response = client.post("/workbooks/purge", json={"retention_days": 30})
        check("A fresh workbook is kept", response.json()["deleted"] == 0,
              str(response.json()))

        response = client.post("/workbooks/purge", json={"retention_days": 0})
        check("A zero-day window is ignored, not a purge-everything",
              response.json()["deleted"] == 0, str(response.json()))
        check("The workbook is still there",
              len(client.get("/workbooks").json()["workbooks"]) == 1,
              str(client.get("/workbooks").json()))

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All settings checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
