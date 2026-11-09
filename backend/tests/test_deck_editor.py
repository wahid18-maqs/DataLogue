"""Checks for the live deck editor: the requester's own changes to a deck."""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.presentation.deck_editor import (  # noqa: E402
    DeckEditError,
    apply_deck_edits,
    editable_fields,
)

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


PLAN = {
    "title": "Sales Overview",
    "subtitle": "A subtitle",
    "slide_count": 3,
    "slides": [
        {
            "index": 1,
            "type": "title",
            "title": "Sales Overview",
            "subtitle": "A subtitle",
            "banner_label": "Executive Summary Highlight",
            "banner_text": "The original highlight.",
            "kpis": [{"label": "Total Sales", "value": "1,213,482.30"}],
        },
        {
            "index": 2,
            "type": "summary",
            "title": "Executive Summary",
            "category": "Executive Briefing",
            "findings": [
                {"title": "Monetary Scale", "desc": "The original description."},
                {"title": "Category Mix", "desc": "Another description."},
            ],
        },
        {
            "index": 3,
            "type": "chart",
            "title": "Sales Trend Over Time",
            "category": "Temporal Analysis",
            "chart_type": "line",
            "caption": "The original caption.",
            "categories": ["2025-01", "2025-02"],
            "series": [{"name": "Sales", "values": [100, 200]}],
        },
    ],
}


def main():
    print("\n[1] The narrative fields are editable")
    check("A title slide exposes its text", editable_fields("title") == {
        "title": "text",
        "subtitle": "text",
        "banner_label": "text",
        "banner_text": "text",
    }, str(editable_fields("title")))
    check("A summary slide exposes its findings",
          editable_fields("summary").get("findings") == "findings",
          str(editable_fields("summary")))
    check("A chart slide exposes its caption",
          editable_fields("chart").get("caption") == "text",
          str(editable_fields("chart")))
    check("An insights slide exposes its two lists",
          editable_fields("insights").get("insights") == "text_list"
          and editable_fields("insights").get("recommendations") == "text_list",
          str(editable_fields("insights")))
    check("An unknown slide type has no editable fields",
          editable_fields("spreadsheet") == {}, str(editable_fields("spreadsheet")))

    print("\n[2] The data-derived fields are not editable")
    for slide_type, field in (("chart", "series"), ("chart", "categories"),
                              ("title", "kpis"), ("summary", "chart_type")):
        check(f"'{field}' is not editable on a {slide_type} slide",
              field not in editable_fields(slide_type),
              str(editable_fields(slide_type)))

    print("\n[3] An edit changes the text")
    plan, applied, rejected = apply_deck_edits(
        PLAN, [{"slide": 1, "field": "banner_text", "value": "A new highlight."}]
    )
    check("The edit is applied", len(applied) == 1, str(applied))
    check("Nothing is rejected", not rejected, str(rejected))
    check("The banner carries the new text",
          plan["slides"][0]["banner_text"] == "A new highlight.",
          plan["slides"][0]["banner_text"])
    check("The original plan is not mutated",
          PLAN["slides"][0]["banner_text"] == "The original highlight.",
          PLAN["slides"][0]["banner_text"])

    print("\n[4] An edit to a list of findings")
    plan, applied, rejected = apply_deck_edits(
        PLAN,
        [{
            "slide": 2,
            "field": "findings",
            "value": [
                {"title": "New heading", "desc": "New description."},
                {"title": "Kept heading", "desc": "Kept description."},
            ],
        }],
    )
    check("The edit is applied", len(applied) == 1, str(applied))
    check("The first finding is replaced",
          plan["slides"][1]["findings"][0]["title"] == "New heading",
          str(plan["slides"][1]["findings"][0]))
    check("The second finding is kept",
          plan["slides"][1]["findings"][1]["title"] == "Kept heading",
          str(plan["slides"][1]["findings"][1]))
    check("The original findings are not mutated",
          PLAN["slides"][1]["findings"][0]["title"] == "Monetary Scale",
          str(PLAN["slides"][1]["findings"][0]))

    print("\n[5] The deck title follows the first slide")
    plan, _, _ = apply_deck_edits(
        PLAN, [{"slide": 1, "field": "title", "value": "A New Deck Title"}]
    )
    check("The deck title is updated", plan["title"] == "A New Deck Title", plan["title"])
    check("The deck subtitle is kept", plan["subtitle"] == "A subtitle", plan["subtitle"])

    print("\n[6] Edits that cannot be applied are reported, not silently dropped")
    plan, applied, rejected = apply_deck_edits(
        PLAN,
        [
            {"slide": 2, "field": "chart_type", "value": "bar"},
            {"slide": 99, "field": "title", "value": "x"},
            {"slide": 1, "field": "banner_text", "value": "ok"},
        ],
    )
    check("The valid edit is applied", len(applied) == 1, str(applied))
    check("Both invalid edits are rejected", len(rejected) == 2, str(rejected))
    check("The chart data edit is named in the reason",
          any("chart_type" in item["reason"] for item in rejected),
          str(rejected))
    check("The missing slide is named in the reason",
          any("does not exist" in item["reason"] for item in rejected),
          str(rejected))
    check("The valid edit still landed",
          plan["slides"][0]["banner_text"] == "ok", plan["slides"][0]["banner_text"])

    print("\n[7] The text is bounded")
    plan, applied, _ = apply_deck_edits(
        PLAN, [{"slide": 1, "field": "banner_text", "value": "x" * 5000}]
    )
    check("A very long text is truncated", len(plan["slides"][0]["banner_text"]) == 500,
          str(len(plan["slides"][0]["banner_text"])))

    plan, _, _ = apply_deck_edits(
        PLAN, [{"slide": 3, "field": "caption", "value": "line one\nline two"}]
    )
    check("A line break in a single-line field is collapsed",
          "\n" not in plan["slides"][2]["caption"],
          repr(plan["slides"][2]["caption"]))

    plan, _, _ = apply_deck_edits(
        PLAN, [{"slide": 1, "field": "banner_text", "value": "  padded  "}]
    )
    check("Surrounding whitespace is trimmed",
          plan["slides"][0]["banner_text"] == "padded",
          repr(plan["slides"][0]["banner_text"]))

    print("\n[8] A list edit is bounded and cleaned")
    plan, _, _ = apply_deck_edits(
        PLAN,
        [{"slide": 1, "field": "banner_text", "value": ""}],
    )
    check("An empty text is allowed", plan["slides"][0]["banner_text"] == "",
          repr(plan["slides"][0]["banner_text"]))

    print("\n[9] A deck with no slides cannot be edited")
    try:
        apply_deck_edits({"slides": []}, [{"slide": 1, "field": "title", "value": "x"}])
        check("An empty deck raises", False, "expected a DeckEditError")
    except DeckEditError:
        check("An empty deck raises", True)

    print("\n[10] The edited plan renders to a real PPTX")
    from pptx import Presentation
    from src.presentation.presentation_generator import render_plan_to_pptx

    plan, _, _ = apply_deck_edits(
        PLAN, [{"slide": 1, "field": "banner_text", "value": "An edited highlight."}]
    )
    output = BASE_DIR / "data" / "presentations" / "_editor_check.pptx"
    render_plan_to_pptx(plan, output)
    check("The file is written", output.exists())
    prs = Presentation(str(output))
    check("It has one slide per planned slide", len(prs.slides) == 3, str(len(prs.slides)))
    text = "\n".join(
        shape.text_frame.text
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_text_frame
    )
    check("The edited text is in the file", "An edited highlight." in text, text[:200])
    check("The original text is not in the file", "The original highlight." not in text)
    output.unlink(missing_ok=True)

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All deck editor checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
