import json
import logging
import math
import re
from typing import Any, Dict, List, Optional

from src.presentation.dataset_document import document_to_json
from src.core.llm import LLMError, generate_response

logger = logging.getLogger(__name__)

# Cap on the tokens the model may generate. The narrative is a short JSON
# object, so a few thousand tokens is ample — and setting it explicitly
# matters: providers reserve the model's whole context window against the
# account balance when no cap is given, and reject the request when the
# balance cannot cover that.
MAX_COMPLETION_TOKENS = 3000

# Why the last agent run failed, if it did. Set by run_deck_agent().
_last_failure: Optional[Dict[str, str]] = None

# Fields the agent must return, and the type each one is expected to have.
_REQUIRED_FIELDS: Dict[str, type] = {
    "banner_highlight": str,
    "executive_summary_sections": list,
    "key_insights": list,
    "core_empirical_observations": list,
    "recommended_next_actions": list,
    "trend_caption": str,
}

# Upper bounds so a chatty response cannot overflow a slide.
_MAX_BANNER_CHARS = 600
_MAX_HEADING_CHARS = 90
_MAX_BODY_CHARS = 420
_MAX_LIST_ITEMS = 5
_MAX_ITEM_CHARS = 320

# The JSON skeleton handed to the model. It mirrors the shape of the deck plan
# so the mapping onto the slides is a straight field-for-field copy.
_JSON_SHAPE = """{
  "banner_highlight": "2-3 sentences (~40 words) for the title slide's Executive Summary Highlight box. Open by characterising what kind of report this is, then state the 2-3 single most important numbers from the KPIs, verbatim.",

  "executive_summary_sections": [
    {
      "heading": "Short section label, e.g. 'Monetary / Volume Scale'",
      "body": "1-2 sentences interpreting the relevant KPIs/findings in plain business language. State the number, then say what it means."
    }
  ],

  "key_insights": [
    "3-5 short, punchy one-line insights, each grounded in a specific number from the findings."
  ],

  "core_empirical_observations": [
    "2-4 bullet-length statements of fact, each citing a specific stat from the findings."
  ],

  "recommended_next_actions": [
    "2-4 concrete, specific recommendations that follow logically from the observations above. Each must name the specific category/segment/metric it applies to."
  ],

  "trend_caption": "One sentence summarising the direction and magnitude of the time-series trend."
}"""

_SLIDE_PLAN_SHAPE = """{
  "slides": [
    {
      "source_id": "an id from the AVAILABLE SLIDES list, 'custom', or 'conclusion'",
      "title": "A concise slide title",
      "chart_type": "bar | line | column",
      "metric": "an exact numeric column name, required for custom",
      "group_by": "an exact categorical or date column name, required for custom"
    }
  ]
}"""


def _build_prompt(
    schema: Dict[str, Any],
    kpis: Dict[str, Any],
    findings: Dict[str, Any],
    document: Optional[Dict[str, Any]] = None,
    suggestions: Optional[str] = None,
) -> str:
    """Build the deck-narrative prompt from the data document and statistics."""
    parts = [
        "You are an analyst writing the narrative content for a business "
        "presentation that has already been built from a dataset.\n"
        "You are given a JSON description of the dataset — its columns, a "
        "profile of every column, and a sample of the actual rows — together "
        "with statistics computed from the whole dataset.\n"
        "Never invent a number that isn't given to you; every figure in your "
        "output must come from the data below, stated exactly as given "
        "(or trivially reformatted, e.g. rounding a percentage you were given).",
    ]

    if document:
        parts.append(
            "DATASET DOCUMENT (JSON):\n"
            + document_to_json(document)
        )

    parts.append(
        "DATASET SCHEMA:\n" + json.dumps(schema, default=str, indent=2)
    )
    parts.append(
        "KEY METRICS (KPIs):\n" + json.dumps(kpis, default=str, indent=2)
    )
    parts.append(
        "COMPUTED FINDINGS (concentration, trends, breakdowns):\n"
        + json.dumps(findings, default=str, indent=2)
    )

    if suggestions and suggestions.strip():
        parts.append(
            "THE REQUESTER ASKED FOR THESE CHANGES:\n"
            + suggestions.strip()
            + "\n\nRewrite the narrative to follow these instructions. They "
            "govern the wording, emphasis, angle and tone of the narrative — "
            "which findings to lead with, how to phrase them, what to "
            "highlight, what to emphasise or tone down.\n"
            "They cannot change the underlying data: every figure "
            "you write must still come from the data above. Slide structure "
            "changes are handled by a separate planner. If a request "
            "would require a number that is not in the data, write around it "
            "instead of inventing one."
        )

    parts.append(
        "Write the narrative content for a business presentation. Return ONLY a "
        "JSON object with this exact structure, no markdown fences, no preamble:\n\n"
        + _JSON_SHAPE
    )

    parts.append(
        "Rules for the sections and lists:\n"
        "- one executive_summary_sections entry per major finding theme present "
        "in the data (scale, concentration, category mix, customer base, "
        "status mix, etc.) — do not invent themes the data does not support\n"
        "- 2-4 core_empirical_observations, 2-4 recommended_next_actions, "
        "3-5 key_insights\n"
        "- no generic filler like 'the data shows interesting patterns'\n"
        "- if a theme is absent from the data, omit it rather than "
        "fabricating content for it\n\n"
        "Tone: confident, analytical, written for an executive audience. No "
        "hedging language ('might', 'could potentially') unless the finding "
        "itself is uncertain."
    )

    return "\n\n".join(parts)


def _strip_code_fence(raw: str) -> str:
    """Remove a surrounding markdown code fence, if the model added one."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)
    return cleaned.strip()


def _clean_text(value: Any, max_chars: int) -> str:
    """Normalise a model-supplied string and clamp its length."""
    if not isinstance(value, str):
        return ""
    collapsed = re.sub(r"\s+", " ", value).strip()
    if len(collapsed) > max_chars:
        collapsed = collapsed[: max_chars - 1].rstrip() + "…"
    return collapsed


def _clean_list(value: Any, max_items: int, max_chars: int) -> List[str]:
    """Normalise a model-supplied list of strings, dropping empties."""
    if not isinstance(value, list):
        return []
    items: List[str] = []
    for entry in value:
        if isinstance(entry, str):
            text = _clean_text(entry, max_chars)
        elif isinstance(entry, dict):
            # Some models return {"text": "..."} for list entries.
            text = _clean_text(entry.get("text") or entry.get("body") or "", max_chars)
        else:
            continue
        if text:
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def _clean_sections(value: Any) -> List[Dict[str, str]]:
    """Normalise the executive-summary sections into heading/body pairs."""
    if not isinstance(value, list):
        return []
    sections: List[Dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        heading = _clean_text(entry.get("heading") or entry.get("title") or "", _MAX_HEADING_CHARS)
        body = _clean_text(entry.get("body") or entry.get("desc") or entry.get("text") or "", _MAX_BODY_CHARS)
        if not heading and not body:
            continue
        sections.append({
            "heading": heading or "Finding",
            "body": body or heading,
        })
        if len(sections) >= _MAX_LIST_ITEMS:
            break
    return sections


def _validate(payload: Any) -> Optional[Dict[str, Any]]:
    """Validate the model's JSON payload; return it cleaned, or None if unusable."""
    if not isinstance(payload, dict):
        return None

    cleaned: Dict[str, Any] = {
        "banner_highlight": _clean_text(payload.get("banner_highlight"), _MAX_BANNER_CHARS),
        "executive_summary_sections": _clean_sections(payload.get("executive_summary_sections")),
        "key_insights": _clean_list(payload.get("key_insights"), _MAX_LIST_ITEMS, _MAX_ITEM_CHARS),
        "core_empirical_observations": _clean_list(
            payload.get("core_empirical_observations"), _MAX_LIST_ITEMS, _MAX_ITEM_CHARS
        ),
        "recommended_next_actions": _clean_list(
            payload.get("recommended_next_actions"), _MAX_LIST_ITEMS, _MAX_ITEM_CHARS
        ),
        "trend_caption": _clean_text(payload.get("trend_caption"), _MAX_BODY_CHARS),
    }

    # The narrative is only usable if it carries real content. A model that
    # answers with an empty object is treated as a failure.
    has_content = bool(
        cleaned["banner_highlight"]
        or cleaned["executive_summary_sections"]
        or cleaned["key_insights"]
        or cleaned["core_empirical_observations"]
        or cleaned["recommended_next_actions"]
    )
    if not has_content:
        return None

    return cleaned

def _numbers_in(text: str) -> set:
    """Extract numeric tokens from a string, for the hallucination check."""
    return set(re.findall(r"\d[\d,]*\.?\d*", text.replace("%", "")))


def _parse_amounts(text: str) -> List[float]:
    """
    Parse every number in a string into a float.

    Handles thousands separators, percentages and K/M/B suffixes, so that
    "1.2M" is understood as 1200000 and "48.3%" as 48.3.
    """
    amounts: List[float] = []
    # A number, optional magnitude suffix, optionally followed by a percent sign.
    # The suffix must not be the start of a word ("14 but" is not 14 billion),
    # hence the negative lookahead.
    pattern = re.compile(
        r"(\d[\d,]*(?:\.\d+)?)\s*([KMB])(?![a-zA-Z])\s*%?"
        r"|(\d[\d,]*(?:\.\d+)?)\s*%?"
    )
    for match in pattern.finditer(text):
        raw = (match.group(1) or match.group(3) or "").replace(",", "")
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (match.group(2) or "").upper()
        if suffix == "K":
            value *= 1_000
        elif suffix == "M":
            value *= 1_000_000
        elif suffix == "B":
            value *= 1_000_000_000
        amounts.append(value)
    return amounts


# Structural numbers that appear in analytical prose without being a
# measurement of the data ("the top 25% of orders", "the 3 main segments").
# Checking these reliably is not possible, so they are exempt.
_STRUCTURAL_NUMBERS = {25, 50, 75, 90, 95, 100}


def _round_to(value: float, digits: int) -> float:
    """Round a value to a given number of significant figures."""
    if value == 0:
        return 0.0
    exponent = int(math.floor(math.log10(abs(value))))
    magnitude = 10 ** (exponent - digits + 1)
    return round(value / magnitude) * magnitude


def _matches_source(value: float, allowed: List[float]) -> bool:
    """
    Return True if a figure the model produced is present in the source data.

    A figure matches when it is within a small relative tolerance of one of
    the source values, which allows for rounding (48.27 -> 48.3) and for
    re-scaling into K/M notation (1213482.30 -> 1.2M).
    """
    for candidate in allowed:
        if abs(candidate - value) <= max(0.05, abs(candidate) * 0.005):
            return True

        # A figure re-scaled into K/M/B and then rounded to one or two
        # significant figures ("1.2M" for 1,213,482.30) still refers to the
        # same quantity, so compare against the rounded forms too.
        for digits in (1, 2):
            for scale in (1, 1_000, 1_000_000, 1_000_000_000):
                candidate_scaled = candidate / scale
                if candidate_scaled <= 0:
                    continue
                rounded = _round_to(candidate_scaled, digits)
                if abs(rounded - value) <= max(0.05, abs(rounded) * 0.005):
                    return True
    return False


def _looks_invented(text: str, allowed: List[float]) -> bool:
    """Return True if the text contains a figure that is not in the source data."""
    for value in _parse_amounts(text):
        if value == int(value):
            # Small integers are far too common in prose ("top 3 products",
            # "2 main segments") to check reliably, so they are exempt.
            if 0 <= value <= 20:
                continue
            if value in _STRUCTURAL_NUMBERS:
                continue
        if not _matches_source(value, allowed):
            return True
    return False


def _sanitize_numbers(payload: Dict[str, Any], source_text: str) -> Dict[str, Any]:
    """
    Remove any part of the narrative that cites a figure not in the data.

    A single bad sentence should not throw away the whole narrative, so the
    offending item is dropped and the rest is kept. Text fields (the banner,
    the trend caption) fall back to empty when they are unusable, which makes
    the caller use the deterministic template instead.
    """
    allowed = _parse_amounts(source_text)

    for field in ("banner_highlight", "trend_caption"):
        if _looks_invented(payload.get(field, ""), allowed):
            payload[field] = ""

    sections: List[Dict[str, str]] = []
    for section in payload.get("executive_summary_sections", []):
        if _looks_invented(section.get("body", ""), allowed):
            logger.warning("Deck agent section dropped: it cited a figure not in the data.")
            continue
        sections.append(section)
    payload["executive_summary_sections"] = sections

    for key in ("key_insights", "core_empirical_observations", "recommended_next_actions"):
        kept: List[str] = []
        for item in payload.get(key, []):
            if _looks_invented(item, allowed):
                logger.warning("Deck agent item dropped: it cited a figure not in the data.")
                continue
            kept.append(item)
        payload[key] = kept

    return payload


def _has_content(payload: Dict[str, Any]) -> bool:
    """Return True if the narrative still carries usable content."""
    return bool(
        payload.get("banner_highlight")
        or payload.get("executive_summary_sections")
        or payload.get("key_insights")
        or payload.get("core_empirical_observations")
        or payload.get("recommended_next_actions")
    )


def _record_failure(reason: str, exc: Optional[Exception] = None) -> None:
    """Remember why the agent failed, so the caller can report it."""
    global _last_failure
    _last_failure = {"reason": reason, "detail": str(exc) if exc else ""}
    logger.warning("Deck agent %s: %s", reason, exc or "")


def last_failure() -> Optional[Dict[str, str]]:
    """Return why the last agent run failed, or None if it succeeded."""
    return _last_failure


def run_deck_agent(
    schema: Dict[str, Any],
    kpis: Dict[str, Any],
    findings: Dict[str, Any],
    document: Optional[Dict[str, Any]] = None,
    suggestions: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Ask the LLM to write the deck's narrative.

    Args:
        schema: The detected dataset schema.
        kpis: The computed KPI payload.
        findings: The computed statistics the narrative may cite.
        document: The dataset document (see ``dataset_document``) that
            describes the columns, their profiles and a sample of the rows.
            When given, the model can read the actual data, not only the
            pre-computed statistics.
        suggestions: Free-text instructions from the requester about how the
            narrative should read — the angle, emphasis or wording they
            want. They guide the prose but cannot introduce new figures.

    Returns the validated narrative dict, or None when the agent is
    unavailable or its answer cannot be trusted. Callers are expected to fall
    back to their deterministic text in that case.
    """
    global _last_failure
    _last_failure = None

    try:
        prompt = _build_prompt(schema, kpis, findings, document, suggestions)
    except (TypeError, ValueError) as exc:
        _record_failure("could not build the prompt", exc)
        return None

    try:
        raw_response = generate_response(prompt, max_tokens=MAX_COMPLETION_TOKENS)
    except LLMError as exc:
        _record_failure("provider unavailable", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - any provider failure degrades gracefully
        _record_failure("provider failed", exc)
        return None

    try:
        payload = json.loads(_strip_code_fence(raw_response))
    except (json.JSONDecodeError, TypeError) as exc:
        _record_failure("returned invalid JSON", exc)
        return None

    cleaned = _validate(payload)
    if cleaned is None:
        _record_failure("returned an empty narrative")
        return None

    source = {"schema": schema, "kpis": kpis, "findings": findings}
    if document:
        source["document"] = document
    source_text = json.dumps(source, default=str)
    cleaned = _sanitize_numbers(cleaned, source_text)

    if not _has_content(cleaned):
        _record_failure("narrative was entirely unusable")
        return None

    logger.info("Deck agent produced a validated narrative.")
    return cleaned


def run_slide_plan_agent(
    schema: Dict[str, Any],
    available_slides: List[Dict[str, Any]],
    current_plan: Optional[Dict[str, Any]] = None,
    request: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Ask the model to choose grounded slides and optionally add chart slides."""
    prompt = (
        "You are planning a business presentation from an already profiled "
        "dataset. Return ONLY JSON matching this shape, with no markdown:\n"
        + _SLIDE_PLAN_SHAPE
        + "\n\nAVAILABLE SLIDES:\n"
        + json.dumps(available_slides, default=str)
        + "\n\nDATASET COLUMNS:\n"
        + json.dumps(schema.get("columns", []), default=str)
        + "\n\nRules:\n"
        "- Keep useful available slides by their exact source_id.\n"
        "- Keep the title slide source_id='title' as the first slide.\n"
        "- You may reorder or omit available slides. If the requester asks "
        "to delete, remove, drop, or omit a slide, do not include that slide.\n"
        "- Never delete the title slide.\n"
        "- If the requester asks for a conclusion, final takeaways, or an "
        "overall conclusion, include source_id='conclusion'.\n"
        "- You may add at most three custom chart slides. For custom slides, "
        "metric and group_by must be exact columns from the dataset; never "
        "invent a column or a number.\n"
        "- Use a custom slide only when it adds a distinct, useful analysis.\n"
        "- Return at least two slides and at most ten slides.\n"
    )
    if current_plan:
        prompt += (
            "\nCURRENT SLIDE PLAN:\n"
            + json.dumps(current_plan, default=str)
            + "\nPreserve existing useful content unless the requester asks "
            "to remove or replace it.\n"
        )
    if request and request.strip():
        prompt += "\nREQUESTER CHANGE:\n" + request.strip()

    try:
        raw = generate_response(prompt, max_tokens=4000)
        payload = json.loads(_strip_code_fence(raw))
    except (LLMError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _record_failure("slide plan unavailable", exc)
        return None

    slides = payload.get("slides") if isinstance(payload, dict) else None
    if not isinstance(slides, list):
        _record_failure("slide plan had no slides")
        return None

    cleaned: List[Dict[str, Any]] = []
    for item in slides[:10]:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        entry = {"source_id": source_id.strip()}
        for key in ("title", "chart_type", "metric", "group_by"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                entry[key] = value.strip()
        cleaned.append(entry)
    if len(cleaned) < 2:
        _record_failure("slide plan contained too few valid slides")
        return None
    return cleaned
