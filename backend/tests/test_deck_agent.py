"""Checks for the deck agent: the LLM that writes a presentation's narrative."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import src.presentation.deck_agent as agent  # noqa: E402
import src.presentation.presentation_generator as generator  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


# A narrative that cites only figures present in the source data.
GOOD_RESPONSE = {
    "banner_highlight": "This report covers 50 sales records totalling 1,213,482.30 across 6 categories.",
    "executive_summary_sections": [
        {
            "heading": "Monetary Scale (Sales)",
            "body": "Total sales reach 1,213,482.30 with an average of 24,269.65 per transaction.",
        },
        {
            "heading": "Category Mix",
            "body": "Grocery leads on volume with 14 records (28.0% of rows).",
        },
    ],
    "key_insights": ["The top 25% of orders carries 68.3% of total value"],
    "core_empirical_observations": ["Delivered is the dominant status at 37 records (74.0%)"],
    "recommended_next_actions": ["Defend Furniture, which leads on revenue with 367,826.80"],
    "trend_caption": "Sales trend upward over the 724-day window.",
}

def sample_frame():
    """
    A small dataset for the deck-plan checks.

    The narrative those checks use carries no figures, so it does not have
    to match this data: the checks are about where the wording comes from,
    not about the numbers.
    """
    import pandas as pd

    rows = []
    for index in range(24):
        rows.append(
            {
                "Order_ID": f"ORD-{index + 1:04d}",
                "Order_Date": f"2024-{((index % 12) + 1):02d}-{(index % 27) + 1:02d}",
                "Customer_Name": f"Customer {index % 8}",
                "Category": ["Furniture", "Office", "Technology"][index % 3],
                "Region": ["North", "South", "East", "West"][index % 4],
                "Quantity": (index % 7) + 1,
                "Sales": 1000.0 + (index * 137.5),
                "Profit": 180.0 + (index * 24.75),
                "Order_Status": "Completed" if index % 4 else "Pending",
            }
        )

    return pd.DataFrame(rows)


# A narrative for the deck-plan checks. It carries no figures, so it
# survives the invented-number check whatever the data turns out to be.
PLAN_RESPONSE = {
    "banner_highlight": "This report covers the trading period across every region.",
    "executive_summary_sections": [
        {
            "heading": "Monetary Scale (Sales)",
            "body": "Total sales and the average transaction are set out below.",
        },
        {
            "heading": "Category Mix",
            "body": "Grocery leads on volume across the period.",
        },
    ],
    "key_insights": ["The top quartile of orders carries the bulk of the value"],
    "core_empirical_observations": ["Delivered is the dominant status across the period"],
    "recommended_next_actions": ["Defend Furniture, which leads on revenue"],
    "trend_caption": "Sales trend upward over the period.",
}


# The statistics the agent is given.
SCHEMA = {
    "total_rows": 50,
    "total_columns": 20,
    "numeric_columns": ["Sales", "Profit"],
    "categorical_columns": ["Category", "Order_Status"],
    "datetime_columns": ["Order_Date"],
}
KPIS = {
    "kpis": [
        {"label": "Total Sales", "formatted": "1,213,482.30"},
        {"label": "Avg Order Value", "formatted": "24,269.65"},
    ]
}
FINDINGS = {
    "total_rows": 50,
    "revenue_total": 1213482.3,
    "revenue_average": 24269.65,
    "revenue_median": 12135.0,
    "top_quartile_value_share_pct": 68.32,
    "category_column": "Category",
    "category_count": 6,
    "top_category": "Grocery",
    "top_category_count": 14,
    "top_category_share_pct": 28.0,
    "top_category_by_revenue": "Furniture",
    "top_category_revenue": 367826.8,
    "status_column": "Order_Status",
    "top_status": "Delivered",
    "top_status_count": 37,
    "top_status_share_pct": 74.0,
    "period_start": "2024-08-07",
    "period_end": "2026-08-01",
    "period_days": 724,
    "data_completeness_pct": 100.0,
}


def with_response(response):
    """Patch the LLM client to return a fixed response."""
    agent.generate_response = lambda prompt, max_tokens=None: response


def capture_prompt():
    """Patch the LLM client to record the prompt it was given."""
    captured = {}

    def _capture(prompt, max_tokens=None):
        captured["prompt"] = prompt
        return json.dumps(GOOD_RESPONSE)

    agent.generate_response = _capture
    return captured


def run_agent():
    return agent.run_deck_agent(SCHEMA, KPIS, FINDINGS)


def main():
    print("\n[1] The agent produces a narrative")
    with_response(json.dumps(GOOD_RESPONSE))
    result = run_agent()
    check("Returns a narrative dict", isinstance(result, dict), str(type(result)))
    check("Keeps the banner highlight", result and result.get("banner_highlight", "").startswith("This report"))
    check("Keeps the executive summary sections", result and len(result.get("executive_summary_sections", [])) == 2)
    check("Keeps the key insights", result and len(result.get("key_insights", [])) == 1)
    check("Keeps the observations", result and len(result.get("core_empirical_observations", [])) == 1)
    check("Keeps the recommended actions", result and len(result.get("recommended_next_actions", [])) == 1)
    check("Keeps the trend caption", result and result.get("trend_caption", "").startswith("Sales trend"))

    print("\n[2] A missing API key degrades to the templates")
    def raise_llm_error(prompt, max_tokens=None):
        raise agent.LLMError("OPENROUTER_API_KEY is not set.")

    agent.generate_response = raise_llm_error
    result = run_agent()
    check("Returns None when the LLM is unavailable", result is None, str(result))
    check("Records why the agent failed",
          (agent.last_failure() or {}).get("reason") == "provider unavailable",
          str(agent.last_failure()))
    check("Records the failure detail",
          "OPENROUTER_API_KEY" in (agent.last_failure() or {}).get("detail", ""),
          str(agent.last_failure()))

    print("\n[3] Invalid responses are rejected")
    agent.generate_response = lambda prompt, max_tokens=None: "this is not json"
    check("Rejects a non-JSON response", run_agent() is None)

    agent.generate_response = lambda prompt, max_tokens=None: json.dumps({"nothing": "useful"})
    check("Rejects a response with no content", run_agent() is None)

    agent.generate_response = lambda prompt, max_tokens=None: "```json\n" + json.dumps(GOOD_RESPONSE) + "\n```"
    result = run_agent()
    check("Accepts a response wrapped in a code fence", result is not None)

    print("\n[4] Invented figures are caught")
    bad = json.loads(json.dumps(GOOD_RESPONSE))
    bad["key_insights"] = ["Revenue is 987,654,321.55 across the board"]
    with_response(json.dumps(bad))
    result = run_agent()
    check("Drops an insight citing an unknown figure",
          result is not None and not result.get("key_insights"),
          str(result.get("key_insights") if result else None))
    check("Keeps the rest of the narrative when one item is bad",
          result is not None and bool(result.get("banner_highlight")))

    bad = json.loads(json.dumps(GOOD_RESPONSE))
    bad["banner_highlight"] = "Total revenue reached 4,321,987.65 this period."
    with_response(json.dumps(bad))
    result = run_agent()
    check("Drops a banner citing an unknown figure",
          result is not None and not result.get("banner_highlight"))

    print("\n[5] Tolerated formatting differences")
    tolerated = json.loads(json.dumps(GOOD_RESPONSE))
    tolerated["banner_highlight"] = "Total sales reached 1.2M across 50 records."
    with_response(json.dumps(tolerated))
    result = run_agent()
    check("Accepts a K/M re-scaled figure",
          result is not None and bool(result.get("banner_highlight")),
          str(result.get("banner_highlight") if result else None))

    tolerated = json.loads(json.dumps(GOOD_RESPONSE))
    tolerated["key_insights"] = ["The top 25% of orders carries 68.3% of total value"]
    with_response(json.dumps(tolerated))
    result = run_agent()
    check("Accepts a structural percentage like 25",
          result is not None and len(result.get("key_insights", [])) == 1)

    tolerated = json.loads(json.dumps(GOOD_RESPONSE))
    tolerated["recommended_next_actions"] = ["It is the largest category at 14 records"]
    with_response(json.dumps(tolerated))
    result = run_agent()
    check("Accepts a small integer that is in the data",
          result is not None and len(result.get("recommended_next_actions", [])) == 1)

    print("\n[6] Number parsing")
    check("Does not read '14 but' as 14 billion",
          agent._parse_amounts("count at 14 but fewer") == [14.0],
          str(agent._parse_amounts("count at 14 but fewer")))
    check("Reads a K suffix", agent._parse_amounts("about 1.2K units") == [1200.0])
    check("Reads an M suffix", agent._parse_amounts("about 1.2M units") == [1200000.0])
    check("Reads a percentage", agent._parse_amounts("68.3% of value") == [68.3])
    check("Reads a thousands separator", agent._parse_amounts("1,213,482.30 total") == [1213482.3])

    print("\n[7] The prompt")
    prompt = agent._build_prompt(SCHEMA, KPIS, FINDINGS)
    check("Includes the schema", "DATASET SCHEMA" in prompt)
    check("Includes the KPIs", "KEY METRICS" in prompt)
    check("Includes the findings", "COMPUTED FINDINGS" in prompt)
    check("Forbids inventing numbers", "Never invent a number" in prompt)
    check("Requests JSON only", "Return ONLY a JSON object" in prompt)
    check("Describes every required field",
          all(field in prompt for field in
              ("banner_highlight", "executive_summary_sections", "key_insights",
               "core_empirical_observations", "recommended_next_actions", "trend_caption")))

    print("\n[7b] The dataset document")
    from src.presentation.dataset_document import build_dataset_document
    import pandas as pd
    frame = pd.DataFrame({
        "order_id": ["ORD-001", "ORD-002", "ORD-003"],
        "region": ["North", "South", "North"],
        "revenue": [120.5, 80.25, 200.0],
    })
    document = build_dataset_document(frame)
    with_document = agent._build_prompt(SCHEMA, KPIS, FINDINGS, document)
    check("The document section is present", "DATASET DOCUMENT" in with_document)
    check("The document carries the column profiles", "column_profiles" in with_document)
    check("The document carries sample rows", "sample_rows" in with_document)
    check("The document carries a real value", "ORD-001" in with_document)
    check("The document section comes before the schema",
          with_document.index("DATASET DOCUMENT") < with_document.index("DATASET SCHEMA"))
    check("Without a document the section is absent",
          "DATASET DOCUMENT" not in prompt)

    print("\n[7c] The requester's suggestions")
    check("Without suggestions the section is absent",
          "THE REQUESTER ASKED" not in prompt)
    with_suggestions = agent._build_prompt(
        SCHEMA, KPIS, FINDINGS, document, "Lead with the Furniture segment."
    )
    check("The suggestions section is present", "THE REQUESTER ASKED" in with_suggestions)
    check("The suggestions are quoted verbatim",
          "Lead with the Furniture segment." in with_suggestions)
    check("The suggestions are told they cannot change the data",
          "cannot change the underlying data" in with_suggestions)
    check("The suggestions come after the findings",
          with_suggestions.index("THE REQUESTER ASKED")
          > with_suggestions.index("COMPUTED FINDINGS"))
    check("Blank suggestions are ignored",
          "THE REQUESTER ASKED" not in agent._build_prompt(
              SCHEMA, KPIS, FINDINGS, document, "   "))

    captured = capture_prompt()
    agent.run_deck_agent(SCHEMA, KPIS, FINDINGS, document, "Focus on the North region.")
    check("The agent sends the suggestions to the provider",
          "Focus on the North region." in captured.get("prompt", ""),
          captured.get("prompt", "")[:80])

    print("\n[8] The deck plan uses the agent's narrative")
    import pandas as pd
    # The dataset is built here rather than read from the uploads folder:
    # the checks are about the narrative, and a shared file that another
    # test writes to would make them depend on each other.
    df = sample_frame()
    if True:
        with_response(json.dumps(PLAN_RESPONSE))
        plan = generator.build_deck_plan(df, use_agent=True)
        slides = plan["slides"]
        check("The banner comes from the agent",
              slides[0]["banner_text"].startswith("This report covers"),
              slides[0]["banner_text"][:60])
        check("The summary sections come from the agent",
              slides[1]["findings"][0]["title"] == "Monetary Scale (Sales)",
              slides[1]["findings"][0]["title"])
        check("The trend caption comes from the agent",
              "upward" in slides[2].get("caption", ""),
              slides[2].get("caption", ""))
        check("The observations come from the agent",
              any("Delivered" in i for i in slides[-1]["insights"]),
              str(slides[-1]["insights"]))
        check("The recommendations come from the agent",
              any("Furniture" in r for r in slides[-1]["recommendations"]),
              str(slides[-1]["recommendations"]))

        print("\n[9] The agent can be switched off")
        with_response(json.dumps(PLAN_RESPONSE))
        plan = generator.build_deck_plan(df, use_agent=False)
        slides = plan["slides"]
        check("The template banner is used",
              slides[0]["banner_text"].startswith("This report delivers evidence-backed"),
              slides[0]["banner_text"][:60])
        check("The template findings are used",
              slides[1]["findings"][0]["title"] == "Monetary / Volume Scale (Sales)",
              slides[1]["findings"][0]["title"])
        check("The template observations are used",
              any("Revenue Concentration" in i for i in slides[-1]["insights"]),
              str(slides[-1]["insights"]))

        print("\n[10] The plan records where the narrative came from")
        with_response(json.dumps(PLAN_RESPONSE))
        plan = generator.build_deck_plan(df, use_agent=True)
        check("Records the agent as the source",
              plan.get("narrative_source") == "agent", str(plan.get("narrative_source")))
        check("Records no error when the agent worked",
              not plan.get("narrative_error"), str(plan.get("narrative_error")))

        agent.generate_response = raise_llm_error
        plan = generator.build_deck_plan(df, use_agent=True)
        check("Records the template as the source",
              plan.get("narrative_source") == "template", str(plan.get("narrative_source")))
        check("Records the error when the agent failed",
              bool(plan.get("narrative_error")), str(plan.get("narrative_error")))
    else:
        print("  SKIP  sample dataset missing")

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All deck agent checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
