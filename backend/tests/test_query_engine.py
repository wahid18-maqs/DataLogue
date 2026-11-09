"""Checks for the query pipeline: schema, intent, plan, sandbox, narration."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

import src.assistant.query_engine as engine  # noqa: E402
from src.assistant.query_sandbox import SandboxError, run_plan  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


DF = pd.DataFrame({
    "category": ["Furniture", "Office", "Furniture", "Grocery", "Office", "Furniture"],
    "region": ["North", "South", "North", "East", "North", "South"],
    "sales": [1000.0, 250.0, 300.0, 500.0, 400.0, 120.0],
    "quantity": [2, 1, 3, 4, 1, 2],
    "order_date": pd.to_datetime([
        "2025-01-05", "2025-01-18", "2025-02-03",
        "2025-02-21", "2025-03-07", "2025-03-25",
    ]),
})


def with_responses(*responses):
    """Patch the LLM client to return the given responses in order."""
    calls = []
    queue = list(responses)

    def _respond(prompt, max_tokens=None):
        calls.append(prompt)
        return queue.pop(0) if queue else "{}"

    engine.generate_response = _respond
    return calls


def main():
    print("\n[1] The schema the model sees")
    schema = engine.detect_schema(DF)
    prompt = engine.build_schema_prompt(DF, schema)
    check("The schema names the row count", '"row_count": 6' in prompt, prompt[:200])
    check("The schema names the columns", '"category"' in prompt)
    check("The schema gives the numeric range", '"min"' in prompt and '"max"' in prompt)
    check("The schema lists the text values", '"values"' in prompt)
    check("The schema marks a date column", '"date"' in prompt, prompt[:400])
    check("The schema gives a date range, not the rows",
          '"from"' in prompt and '"to"' in prompt, prompt[:400])

    print("\n[2] Intent classification")
    with_responses(json.dumps({"intent": "compute", "reason": "Needs a total."}))
    result = engine.classify_intent(prompt, "What is the total sales?")
    check("A computational question is classified as compute",
          result["intent"] == "compute", str(result))
    check("The reason is kept", "total" in result["reason"].lower(), str(result))

    with_responses(json.dumps({"intent": "describe", "reason": "About the shape."}))
    result = engine.classify_intent(prompt, "What columns are there?")
    check("A question about the shape is classified as describe",
          result["intent"] == "describe", str(result))

    with_responses("not json at all")
    result = engine.classify_intent(prompt, "What is the total sales?")
    check("An unreadable answer falls back to compute",
          result["intent"] == "compute", str(result))

    print("\n[3] Plan generation")
    plan = {
        "filters": [],
        "group_by": "category",
        "metrics": [{"column": "sales", "agg": "sum", "as": "total_sales"}],
        "order": {"column": "total_sales", "by": "desc"},
        "limit": {"mode": "head", "count": 3},
    }
    with_responses(json.dumps(plan))
    generated = engine.generate_plan(prompt, "Total sales by category")
    check("The plan is parsed", generated.get("group_by") == "category", str(generated))
    check("The metrics are parsed", len(generated.get("metrics", [])) == 1, str(generated))

    with_responses("not json")
    check("An unreadable plan is empty", engine.generate_plan(prompt, "x") == {})

    print("\n[4] The sandbox computes over the real data")
    result = run_plan(DF, {
        "group_by": "category",
        "metrics": [{"column": "sales", "agg": "sum", "as": "total"}],
    })
    totals = {row["category"]: row["total"] for row in result["rows"]}
    check("Furniture totals 1420", totals.get("Furniture") == 1420.0, str(totals))
    check("Office totals 650", totals.get("Office") == 650.0, str(totals))
    check("Grocery totals 500", totals.get("Grocery") == 500.0, str(totals))

    result = run_plan(DF, {
        "filters": [{"column": "region", "op": "eq", "value": "North"}],
        "metrics": [{"column": "sales", "agg": "sum", "as": "total"}],
    })
    check("A filter is applied", result["rows"][0]["total"] == 1700.0, str(result["rows"]))

    result = run_plan(DF, {
        "group_by": "category",
        "metrics": [{"column": "sales", "agg": "sum", "as": "total"}],
        "order": {"column": "total", "by": "desc"},
        "limit": {"mode": "head", "count": 1},
    })
    check("The order and the limit are applied",
          len(result["rows"]) == 1 and result["rows"][0]["category"] == "Furniture",
          str(result["rows"]))

    result = run_plan(DF, {"metrics": [{"column": None, "agg": "count", "as": "rows"}]})
    check("The rows are counted", result["rows"][0]["rows"] == 6, str(result["rows"]))

    result = run_plan(DF, {
        "group_by": "region",
        "metrics": [{"column": "quantity", "agg": "nunique", "as": "distinct"}],
    })
    check("A distinct count is computed",
          {row["region"]: row["distinct"] for row in result["rows"]}.get("North") == 3,
          str(result["rows"]))

    print("\n[5] The sandbox refuses what it cannot do")
    for label, plan in (
        ("An unknown column", {"metrics": [{"column": "nope", "agg": "sum"}]}),
        ("An unknown aggregation", {"metrics": [{"column": "sales", "agg": "exec"}]}),
        ("An unknown filter", {"filters": [{"column": "region", "op": "system", "value": "x"}]}),
        ("An unknown grouping", {"group_by": "nope",
                                 "metrics": [{"column": "sales", "agg": "sum"}]}),
        ("A non-numeric comparison", {"filters": [{"column": "sales", "op": "gt",
                                                   "value": "text"}]}),
        ("A missing metric", {"group_by": "category"}),
    ):
        try:
            run_plan(DF, plan)
            check(f"{label} is rejected", False, "it was allowed")
        except SandboxError:
            check(f"{label} is rejected", True)

    try:
        run_plan(DF, {"metrics": [{"column": "sales", "agg": "sum"}],
                      "limit": {"mode": "head", "count": 99999}})
        check("An oversized limit is rejected", False, "it was allowed")
    except SandboxError:
        check("An oversized limit is rejected", True)

    print("\n[6] The whole pipeline")
    plan = {
        "filters": [],
        "group_by": "category",
        "metrics": [{"column": "sales", "agg": "sum", "as": "total_sales"}],
        "order": {"column": "total_sales", "by": "desc"},
        "limit": {"mode": "head", "count": 3},
    }
    calls = with_responses(
        json.dumps({"intent": "compute", "reason": "Needs totals."}),
        json.dumps(plan),
        json.dumps({
            "answer": "Furniture leads with 1,420 in sales, followed by Office at 650.",
            "confidence": "high",
        }),
    )
    result = engine.answer_question(DF, "What are the total sales by category?")
    check("The answer is the model's phrasing",
          "Furniture" in result["answer"], result["answer"])
    check("The confidence is carried through", result["confidence"] == "high",
          str(result["confidence"]))
    check("The intent is reported", result["intent"] == "compute", str(result["intent"]))
    check("The supporting data is the computed table",
          result["supporting_data"]["kind"] == "table"
          and result["supporting_data"]["rows"][0]["total_sales"] == 1420.0,
          str(result["supporting_data"])[:200])
    check("The plan is reported", result["plan"].get("group_by") == "category",
          str(result["plan"]))
    check("The model was asked three times", len(calls) == 3, str(len(calls)))
    # The first two calls carry the schema; only the third carries the
    # computed result. Neither carries the raw rows.
    check("The schema calls do not carry the raw rows",
          all("2025-01-05 00:00:00" not in call for call in calls[:2]),
          "a raw row reached the schema prompt")
    check("Only the narration call carries the result",
          "1420.0" in calls[2] and "1420.0" not in calls[0] and "1420.0" not in calls[1],
          "the result reached the schema prompt")

    print("\n[7] Clear aggregates work without a generated plan")
    with_responses(
        json.dumps({"intent": "compute", "reason": "Needs a total."}),
        "{}",
        json.dumps({"answer": "Total sales are 2,570.", "confidence": "high"}),
    )
    result = engine.answer_question(DF, "What is the total sales?")
    check("A local fallback plan is used",
          result["plan"]["metrics"][0]["agg"] == "sum", str(result["plan"]))
    check("The fallback computes the real total",
          result["supporting_data"]["rows"][0]["sum_sales"] == 2570.0,
          str(result["supporting_data"]))
    check("The fallback still narrates the result",
          "2,570" in result["answer"], result["answer"])

    print("\n[7] A question about the shape needs no computation")
    with_responses(json.dumps({"intent": "describe", "reason": "About the shape."}))
    result = engine.answer_question(DF, "What columns does this dataset have?")
    check("The shape is described", "category" in result["answer"], result["answer"])
    check("The intent is describe", result["intent"] == "describe", str(result["intent"]))
    check("The column list is the supporting data",
          "columns" in result["supporting_data"], str(result["supporting_data"])[:120])

    print("\n[8] Failures are reported, not guessed around")
    with_responses("not json")
    result = engine.answer_question(DF, "What columns does this dataset have?")
    check("An unusable plan is reported", "could not work out" in result["answer"],
          result["answer"])
    check("The confidence is low", result["confidence"] == "low", str(result["confidence"]))

    with_responses(
        json.dumps({"intent": "compute", "reason": "Needs totals."}),
        json.dumps({"group_by": "nope", "metrics": [{"column": "sales", "agg": "sum"}]}),
    )
    result = engine.answer_question(DF, "What is the total value by unknown_group?")
    check("A plan that cannot run is reported", "could not answer" in result["answer"],
          result["answer"])
    check("The reason is carried", "nope" in result["answer"], result["answer"])
    check("The confidence is low", result["confidence"] == "low", str(result["confidence"]))

    print("\n[9] An empty question is refused")
    try:
        engine.answer_question(DF, "   ")
        check("An empty question raises", False, "expected a ValueError")
    except ValueError:
        check("An empty question raises", True)

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All query engine checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
