"""Applies the requester's live edits to a deck plan."""

import copy
from typing import Any, Dict, List, Optional, Tuple

# The longest single text an edit may set.
MAX_TEXT_CHARS = 500

# The longest a list item (an observation, a recommendation) may be.
MAX_ITEM_CHARS = 400

# How many items a list field may hold after an edit.
MAX_LIST_ITEMS = 8

# How many findings the summary slide may hold after an edit.
MAX_FINDINGS = 6

# Which fields of which slide type may be edited, and what shape their value
# takes: "text" is a string, "text_list" is a list of strings, and "findings"
# is a list of {"title", "desc"} objects.
EDITABLE_FIELDS: Dict[str, Dict[str, str]] = {
    "title": {
        "title": "text",
        "subtitle": "text",
        "banner_label": "text",
        "banner_text": "text",
    },
    "summary": {
        "title": "text",
        "category": "text",
        "findings": "findings",
    },
    "chart": {
        "title": "text",
        "category": "text",
        "caption": "text",
    },
    "insights": {
        "title": "text",
        "category": "text",
        "insights": "text_list",
        "recommendations": "text_list",
    },
}


class DeckEditError(ValueError):
    """Raised when an edit request is not usable at all."""


def editable_fields(slide_type: str) -> Dict[str, str]:
    """The fields of a slide type that may be edited."""
    return EDITABLE_FIELDS.get(slide_type, {})


def _clean_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Normalise a text edit to a bounded string."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # Collapse the newlines a single-line field cannot show.
    text = " ".join(text.split())
    return text[:limit]


def _clean_list(value: Any) -> List[str]:
    """Normalise a list edit to a bounded list of non-empty strings."""
    if not isinstance(value, list):
        raise DeckEditError("Expected a list of strings.")
    items = [_clean_text(item, MAX_ITEM_CHARS) for item in value]
    return [item for item in items if item][:MAX_LIST_ITEMS]


def _clean_findings(value: Any) -> List[Dict[str, str]]:
    """Normalise a findings edit to a bounded list of titled findings."""
    if not isinstance(value, list):
        raise DeckEditError("Expected a list of findings.")
    findings = []
    for item in value[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"), 200)
        if not title:
            continue
        findings.append(
            {
                "title": title,
                "desc": _clean_text(item.get("desc"), MAX_ITEM_CHARS),
            }
        )
    return findings


def apply_deck_edits(
    plan: Dict[str, Any], edits: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Apply a list of edits to a deck plan.

    Args:
        plan: The deck plan the edits apply to. It is never mutated.
        edits: A list of ``{"slide": <1-based slide number>, "field": str,
            "value": Any}`` objects.

    Returns:
        A tuple of (new plan, applied edits, rejected edits). A rejected edit
        carries a ``reason`` explaining why it was not applied.

    Raises:
        DeckEditError: If the plan has no slides to edit.
    """
    updated = copy.deepcopy(plan or {})
    slides = updated.get("slides") or []
    if not slides:
        raise DeckEditError("The deck has no slides to edit.")

    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for edit in edits or []:
        number = edit.get("slide")
        field = edit.get("field")
        value = edit.get("value")

        if not isinstance(number, int) or isinstance(number, bool):
            rejected.append({"edit": edit, "reason": "The slide number must be an integer."})
            continue
        if not 1 <= number <= len(slides):
            rejected.append({"edit": edit, "reason": f"Slide {number} does not exist."})
            continue

        slide = slides[number - 1]
        spec = editable_fields(slide.get("type", ""))
        if field not in spec:
            rejected.append(
                {
                    "edit": edit,
                    "reason": f"'{field}' is not an editable field of a {slide.get('type')} slide.",
                }
            )
            continue

        kind = spec[field]
        try:
            if kind == "text":
                slide[field] = _clean_text(value)
            elif kind == "text_list":
                slide[field] = _clean_list(value)
            elif kind == "findings":
                slide[field] = _clean_findings(value)
        except DeckEditError as exc:
            rejected.append({"edit": edit, "reason": str(exc)})
            continue

        applied.append({"slide": number, "field": field})

    # The deck title and subtitle mirror the first slide, so they follow an
    # edit to it.
    if slides:
        updated["title"] = slides[0].get("title", updated.get("title", ""))
        updated["subtitle"] = slides[0].get("subtitle", updated.get("subtitle", ""))

    return updated, applied, rejected
