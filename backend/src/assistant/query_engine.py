"""Answers questions about the uploaded dataset, by computing the answer."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.llm import LLMError, active_model, active_provider, generate_response
from src.assistant.query_guardrails import (
    INTENT_ABOUT,
    INTENT_COMPUTE,
    INTENT_DESCRIBE,
    INTENT_OUT_OF_SCOPE,
    SCOPE_STATEMENT,
    TOPIC_MODEL,
    VALID_INTENTS,
    GuardrailError,
    answer_about_self,
    answer_dataset_info,
    apply_response_policy,
    check_question,
    detect_self_topics,
    detect_topics,
    is_dataset_info_question,
    is_off_topic,
    out_of_scope_answer,
)
from src.assistant.query_sandbox import SandboxError, run_plan
from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = "low"
VALID_CONFIDENCE_LEVELS = {"low", "medium", "high"}

# How many rows of the dataset are shown to the model as a sample.
SCHEMA_SAMPLE_ROWS = 5

# The most tokens the plan may use.
PLAN_MAX_TOKENS = 800

# The most tokens the narration may use.
NARRATION_MAX_TOKENS = 800


# ---------------------------------------------------------------------------
# Step 1: schema extraction
# ---------------------------------------------------------------------------


def _column_summary(df: pd.DataFrame, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Describe each column: its type, its range, and a few sample values."""
    summaries: List[Dict[str, Any]] = []

    for column in df.columns:
        series = df[column]
        entry: Dict[str, Any] = {
            "name": str(column),
            "type": "number",
        }

        if pd.api.types.is_datetime64_any_dtype(series):
            entry["type"] = "date"
            dates = series.dropna()
            if not dates.empty:
                entry["from"] = dates.min().isoformat()
                entry["to"] = dates.max().isoformat()
        elif pd.api.types.is_numeric_dtype(series):
            numbers = series.dropna().astype(float)
            entry["type"] = "number"
            if not numbers.empty:
                entry["min"] = round(float(numbers.min()), 4)
                entry["max"] = round(float(numbers.max()), 4)
        else:
            entry["type"] = "text"
            counts = series.dropna().value_counts()
            entry["distinct"] = int(len(counts))
            # The most common values are the sample: they are what the model
            # needs to write a filter the sandbox can apply.
            entry["values"] = [str(value) for value in counts.head(8).index]

        summaries.append(entry)

    return summaries


def build_schema_prompt(df: pd.DataFrame, schema: Dict[str, Any]) -> str:
    """The description of the dataset that the model works from."""
    document = {
        "row_count": int(df.shape[0]),
        "columns": _column_summary(df, schema),
    }
    return json.dumps(document, default=str, indent=2)


# ---------------------------------------------------------------------------
# Step 2 and 3: intent classification and plan generation
# ---------------------------------------------------------------------------


_INTENT_PROMPT = """You decide how a question should be answered.

Answer with a single JSON object and nothing else:
{"intent": "compute" | "describe" | "about" | "out_of_scope", "reason": "one short sentence"}

Classify the user's actual request, not a broader topic that happens to be
related. A simple question should receive a simple answer; do not expand a
question about the model into provider, architecture, privacy, or scope
details unless those are explicitly requested. Questions about the
application and its capabilities belong to "about", not "out_of_scope".

Use "compute" when the answer needs a number that must be calculated from
the rows: totals, averages, counts, comparisons, rankings, breakdowns by a
category, trends over time, or anything filtered by a condition.

Use "describe" when the question is about the shape of the dataset itself
rather than a figure in it: what columns exist, how many rows there are,
what a column contains, or what the data is about.

Use "about" when the question is about the assistant itself rather than
about the data: which model it uses, how its pipeline works, what it can
and cannot do, or what it is for.

Use "out_of_scope" for anything else. The assistant is a data analyst, not
a general-purpose assistant, so most questions outside the dataset are out
of scope.

The assistant's scope:
{scope}

The dataset:
{schema}
"""

_PLAN_PROMPT = """You write a query plan that answers a question about a dataset.

The plan is carried out on the dataframe with pandas. You do not compute
the answer yourself — you describe the computation, and the answer is
produced from the data.

Return a single JSON object with these keys:

"filters": a list of filters, each {"column": "<name>", "op": "<op>", "value": <value>}.
  The ops are: "eq", "ne", "gt", "gte", "lt", "lte", "contains", "in",
  "notnull", "isnull". Use [] when nothing needs filtering.

"group_by": a column name, a list of column names, or null. Use null when
  the question is about the whole dataset rather than a breakdown.

"metrics": a list of metrics, each {"column": "<name>", "agg": "<agg>", "as": "<label>"}.
  The aggs are: "sum", "mean", "median", "min", "max", "count", "nunique",
  "std", "var", "size". For "count" and "size" the column may be null, to
  count the rows in each group. The "as" label is optional; without it a
  label is made from the aggregation and the column.

"order": {"column": "<name>", "by": "asc" | "desc"}, or null. Use it to put
  the largest or smallest first.

"limit": {"mode": "head" | "tail", "count": <integer>}, or null. Use it to
  keep only the top or bottom few rows.

Give an empty metrics list only when the question asks for the rows
themselves rather than a figure over them.

The dataset:
{schema}

The question: {question}
"""


def _strip_code_fence(raw_response: str) -> str:
    """Remove a surrounding markdown code fence (e.g. ```json ... ```)."""
    cleaned = raw_response.strip().strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[len("json"):].strip()
    return cleaned


def _parse_json(raw_response: str) -> Optional[Any]:
    """Parse a JSON object out of a model response, or return None."""
    try:
        return json.loads(_strip_code_fence(raw_response))
    except (json.JSONDecodeError, AttributeError):
        return None


def classify_intent(schema_prompt: str, question: str) -> Dict[str, str]:
    """
    Decide how the question should be answered.

    Returns:
        {"intent": "compute" | "describe" | "about" | "out_of_scope",
         "reason": str}
    """
    prompt = _INTENT_PROMPT.replace("{scope}", SCOPE_STATEMENT)
    prompt = prompt.replace("{schema}", schema_prompt)
    prompt += f"\nThe question: {question}\n"

    try:
        raw = generate_response(prompt, max_tokens=200)
    except LLMError as exc:
        logger.warning("Intent classification failed: %s", exc)
        # When the intent cannot be decided, compute: it is the stronger path.
        return {"intent": INTENT_COMPUTE, "reason": "The intent could not be classified."}

    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return {"intent": INTENT_COMPUTE, "reason": "The intent could not be classified."}

    intent = str(parsed.get("intent", "")).lower()
    if intent not in VALID_INTENTS:
        intent = INTENT_COMPUTE

    return {
        "intent": intent,
        "reason": str(parsed.get("reason", "")).strip(),
    }


def generate_plan(schema_prompt: str, question: str) -> Dict[str, Any]:
    """
    Ask the model for the plan that answers a question.

    Returns:
        The plan as a dict. An empty dict means the model could not produce
        one.
    """
    prompt = _PLAN_PROMPT.replace("{schema}", schema_prompt).replace("{question}", question)

    try:
        raw = generate_response(prompt, max_tokens=PLAN_MAX_TOKENS)
    except LLMError as exc:
        logger.warning("Plan generation failed: %s", exc)
        return {}

    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("The plan was not a JSON object.")
        return {}

    return parsed


def _local_plan_fallback(df: pd.DataFrame, question: str) -> Dict[str, Any]:
    """Build a safe plan for an unambiguous aggregate without an LLM."""
    text = question.lower()
    aggregations = (
        (("average", "mean", "avg"), "mean"),
        (("median",), "median"),
        (("maximum", "max", "highest"), "max"),
        (("minimum", "min", "lowest"), "min"),
        (("count", "how many", "number of"), "count"),
        (("total", "sum"), "sum"),
    )
    aggregation = next(
        (agg for words, agg in aggregations if any(word in text for word in words)),
        None,
    )
    if aggregation is None:
        return {}

    numeric_columns = [
        str(column)
        for column in df.columns
        if pd.api.types.is_numeric_dtype(df[column])
    ]
    if aggregation == "count" and not numeric_columns:
        metric_column = None
    else:
        candidates = [
            column for column in numeric_columns
            if re.search(rf"\b{re.escape(column.lower())}\b", text)
        ]
        if len(candidates) != 1:
            return {}
        metric_column = candidates[0]

    group_by = None
    group_match = re.search(r"\b(?:by|per|each)\s+([a-zA-Z_][\w ]*)", text)
    if group_match:
        phrase = group_match.group(1).strip()
        matches = [
            str(column) for column in df.columns
            if phrase == str(column).lower()
        ]
        if len(matches) != 1:
            return {}
        group_by = matches[0]

    return {
        "group_by": group_by,
        "metrics": [{
            "column": metric_column,
            "agg": aggregation,
            "as": f"{aggregation}_{metric_column or 'rows'}",
        }],
    }


def _repair_ranking_plan(
    df: pd.DataFrame, question: str, plan: Dict[str, Any]
) -> Dict[str, Any]:
    """Make product/category ranking questions aggregate over the right rows."""
    text = question.lower()
    ranking_words = ("highest", "most", "top", "best", "lowest", "least")
    quantity_words = ("sold", "sales", "units", "quantity")
    if not any(word in text for word in ranking_words):
        return plan
    if not any(word in text for word in quantity_words):
        return plan

    product_candidates = [
        str(column)
        for column in df.columns
        if re.search(r"(product|item|category|model|sku)", str(column), re.IGNORECASE)
        and not str(column).lower().startswith("unnamed")
    ]
    product_column = next(
        (column for column in product_candidates if "product" in column.lower()),
        None,
    ) or next(
        (column for column in product_candidates if "category" in column.lower()),
        None,
    ) or (product_candidates[0] if product_candidates else None)
    numeric_columns = [
        str(column)
        for column in df.columns
        if pd.api.types.is_numeric_dtype(df[column])
    ]
    metric_column = next(
        (
            column
            for column in numeric_columns
            if re.search(r"(units?\s*sold|quantity|number\s*sold)", column, re.IGNORECASE)
        ),
        None,
    )
    if metric_column is None:
        metric_column = next(
            (
                column
                for column in numeric_columns
                if re.search(r"(gross\s*sales|net\s*sales|revenue|sales)", column, re.IGNORECASE)
            ),
            None,
        )
    if not product_column or not metric_column:
        return plan

    descending = not any(word in text for word in ("lowest", "least"))
    alias = f"sum_{metric_column}"
    ordinal_match = re.search(
        r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\b",
        text,
    )
    ordinal_counts = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5,
    }
    rank = ordinal_counts.get(ordinal_match.group(1), 1) if ordinal_match else 1
    return {
        **plan,
        "filters": [
            *(
                plan.get("filters", [])
                if isinstance(plan.get("filters"), list)
                else []
            ),
            {"column": product_column, "op": "notnull", "value": True},
        ],
        "group_by": product_column,
        "metrics": [{"column": metric_column, "agg": "sum", "as": alias}],
        "order": {"column": alias, "by": "desc" if descending else "asc"},
        "limit": {"mode": "head", "count": rank},
    }


# ---------------------------------------------------------------------------
# Step 5: result narration
# ---------------------------------------------------------------------------

_NARRATION_PROMPT = """You are a data analyst answering a question about a dataset.

You are given the result of a computation that was carried out on the actual
data, and the question it answers. Write the answer in plain language.

Rules:
- Every figure you give must come from the result. Never do arithmetic
  yourself and never introduce a number that is not in the result.
- If the result does not answer the question, say so plainly.
- Answer only what was asked. Do not add sections about yourself, the
  model, the provider, the architecture, or your own configuration.
- Be brief: one or two sentences for a simple question, three at most for
  a technical one. No preamble, no closing offer of further help.

Return a single JSON object and nothing else:
{"answer": "<the answer>", "confidence": "low" | "medium" | "high"}

Use "high" when the result answers the question directly and completely,
"medium" when it answers it in part, and "low" when it does not.

The question: {question}

The computed result:
{result}
"""


def narrate_result(question: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn a computed result into an answer.

    Returns:
        {"answer": str, "confidence": str}
    """
    prompt = _NARRATION_PROMPT.replace(
        "{question}", question
    ).replace("{result}", json.dumps(result, default=str, indent=2))

    try:
        raw = generate_response(prompt, max_tokens=NARRATION_MAX_TOKENS)
    except LLMError as exc:
        logger.warning("Narration failed: %s", exc)
        return {
            "answer": "The answer was computed, but it could not be phrased.",
            "confidence": DEFAULT_CONFIDENCE,
        }

    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return {
            "answer": str(raw).strip(),
            "confidence": DEFAULT_CONFIDENCE,
        }

    confidence = str(parsed.get("confidence", DEFAULT_CONFIDENCE)).lower()
    if confidence not in VALID_CONFIDENCE_LEVELS:
        confidence = DEFAULT_CONFIDENCE

    return {
        "answer": str(parsed.get("answer", "")).strip(),
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def _describe_only(df: pd.DataFrame, schema: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Answer a question about the shape of the dataset, without computing."""
    document = {
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "columns": _column_summary(df, schema),
    }
    return {
        "answer": (
            f"This dataset has {df.shape[0]} rows and {df.shape[1]} columns: "
            + ", ".join(str(column) for column in df.columns)
            + "."
        ),
        "confidence": "medium",
        "supporting_data": document,
        "intent": "describe",
    }


def answer_question(df: pd.DataFrame, question: str) -> Dict[str, Any]:
    """
    Answer a natural language question about the given dataframe.

    The guardrails run first: a question that is empty, too long, tries to
    redirect the assistant, or asks it to run code is refused before any
    model is called.

    Returns a dict with:
      - "answer": the answer, in plain language
      - "confidence": "low" / "medium" / "high"
      - "supporting_data": the computed rows and numbers behind the answer
      - "intent": "compute" / "describe" / "about" / "out_of_scope"
      - "plan": the plan that was run, when there was one

    On failure the answer explains what went wrong and the confidence is
    "low", rather than a guess.
    """
    question = check_question(question)

    # A question that is plainly off-topic is redirected without asking the
    # model, so the same joke gets the same one-sentence answer every time.
    if is_off_topic(question):
        answered = out_of_scope_answer()
        answered["plan"] = None
        return answered

    # Dataset metadata is answered directly from the active dataframe. This
    # avoids asking the model to identify a file or invent its contents.
    if is_dataset_info_question(question):
        described = answer_dataset_info(df)
        described["plan"] = None
        return described

    # A question that names a topic about the assistant or the application,
    # and shows no sign of asking for a figure, is answered from the
    # verified configuration. No model is involved, so the answer is
    # grounded in the configuration rather than in the model's opinion of
    # itself.
    self_topics = detect_self_topics(question)
    if self_topics:
        answered = answer_about_self(self_topics)
        answered["plan"] = None
        return answered

    schema = detect_schema(df)
    schema_prompt = build_schema_prompt(df, schema)

    intent = classify_intent(schema_prompt, question)

    if intent["intent"] == INTENT_ABOUT:
        # The classifier found a question about the assistant that the
        # deterministic path did not catch. Answer it from the same
        # verified configuration.
        topics = detect_topics(question) or {TOPIC_MODEL}
        answered = answer_about_self(topics)
        answered["plan"] = None
        return answered

    if intent["intent"] == INTENT_OUT_OF_SCOPE:
        answered = out_of_scope_answer()
        answered["plan"] = None
        return answered

    if intent["intent"] == INTENT_DESCRIBE:
        described = _describe_only(df, schema, question)
        described["plan"] = None
        return described

    plan = generate_plan(schema_prompt, question)
    if not plan:
        plan = _local_plan_fallback(df, question)
        if not plan:
            return {
                "answer": "I could not work out how to answer that from this dataset.",
                "confidence": DEFAULT_CONFIDENCE,
                "supporting_data": {},
                "intent": INTENT_COMPUTE,
                "plan": None,
            }
    plan = _repair_ranking_plan(df, question, plan)

    try:
        computed = run_plan(df, plan)
    except SandboxError as exc:
        logger.info("The plan could not be run: %s", exc)
        return {
            "answer": f"I could not answer that from this dataset ({exc}).",
            "confidence": DEFAULT_CONFIDENCE,
            "supporting_data": {},
            "intent": INTENT_COMPUTE,
            "plan": plan,
            "error": str(exc),
        }

    narration = narrate_result(question, computed)

    return {
        "answer": apply_response_policy(narration["answer"], "data"),
        "confidence": narration["confidence"],
        "supporting_data": computed,
        "intent": INTENT_COMPUTE,
        "plan": plan,
    }
