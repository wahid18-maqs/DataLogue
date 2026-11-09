"""Guardrails for the assistant: what it will answer, and how briefly."""

import os
import re
from typing import Any, Dict, List, Optional, Set

from src.core.llm import active_model, active_provider

# The longest question that reaches the model.
MAX_QUESTION_CHARS = 1000

# The intents the assistant recognises. "compute" and "describe" are
# answered from the data; "about" is answered from the verified
# configuration; anything else is out of scope.
INTENT_COMPUTE = "compute"
INTENT_DESCRIBE = "describe"
INTENT_ABOUT = "about"
INTENT_OUT_OF_SCOPE = "out_of_scope"

VALID_INTENTS = {INTENT_COMPUTE, INTENT_DESCRIBE, INTENT_ABOUT, INTENT_OUT_OF_SCOPE}

# The topics a question about the assistant or the application can ask for.
# Each one is answered separately, and only the ones asked for appear.
TOPIC_MODEL = "model"
TOPIC_PROVIDER = "provider"
TOPIC_APP_ARCHITECTURE = "app_architecture"
TOPIC_MODEL_ARCHITECTURE = "model_architecture"
TOPIC_PIPELINE = "pipeline"
TOPIC_CAPABILITIES = "capabilities"
TOPIC_CREATOR = "creator"

ALL_TOPICS = {
    TOPIC_MODEL,
    TOPIC_PROVIDER,
    TOPIC_APP_ARCHITECTURE,
    TOPIC_MODEL_ARCHITECTURE,
    TOPIC_PIPELINE,
    TOPIC_CAPABILITIES,
    TOPIC_CREATOR,
}

# The most sentences an answer may have, by topic. The rule is "answer only
# what was asked", so a question about one thing gets one thing.
TOPIC_SENTENCE_BUDGET = {
    TOPIC_MODEL: 1,
    TOPIC_PROVIDER: 1,
    TOPIC_APP_ARCHITECTURE: 2,
    TOPIC_MODEL_ARCHITECTURE: 2,
    TOPIC_PIPELINE: 2,
    TOPIC_CAPABILITIES: 2,
    TOPIC_CREATOR: 1,
}

# Sections the assistant must never append to an answer of its own accord.
_UNSOLICITED_SECTION_HEADINGS = (
    "verified configuration",
    "provider",
    "scope",
    "internal architecture",
    "architecture",
    "limitations",
    "security notes",
    "notes",
)


class GuardrailError(ValueError):
    """
    Raised when a question is refused before it reaches the model.

    Carries a machine-readable ``code`` so the caller can tell an injection
    attempt from an empty question, and a message that is safe to show the
    user as-is.
    """

    def __init__(self, message: str, code: str = "refused"):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Layer 1: the hard refusals
# ---------------------------------------------------------------------------

# Questions that try to redirect the assistant away from its task. These are
# refused outright: the assistant is not a general-purpose assistant, and a
# question that ignores its scope has left the scope.
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|preceding|earlier|your)\s+"
    r"(?:instructions?|prompts?|rules?|directions?)",
    r"disregard\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|preceding|system|your)\s+"
    r"(?:instructions?|prompts?|rules?)",
    r"forget\s+(?:all\s+|your\s+|the\s+)*(?:previous|prior|earlier|system|your)\s*"
    r"(?:instructions?|prompts?|rules?)",
    r"(?:reveal|show|print|repeat|output|echo|display|give)\s+(?:me\s+)?(?:your|the)\s+"
    r"(?:system|initial|original|hidden|full|developer)\s*"
    r"(?:prompt|instructions?|rules?|message)",
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"(?:act|behave|pretend|roleplay|role-play)\s+as\s+(?:a|an|the)\b",
    r"developer\s+mode|jailbreak|\bDAN\s+mode\b|bypass\s+(?:the\s+|your\s+)?"
    r"(?:guardrail|restriction|filter|safeguard|rule)",
    r"(?:what|which)\s+(?:are|is)\s+your\s+original\s+instructions?",
]

# Requests for the assistant to run code. The assistant never executes
# anything a question asks for; it only computes over the uploaded data.
_CODE_PATTERNS = [
    r"\b(?:eval|exec|compile)\s*\(",
    r"\bos\.system\s*\(",
    r"\bsubprocess\.\w+\s*\(",
    r"\bimport\s+(?:os|subprocess|sys|socket|shutil)\b",
    r"\brm\s+-rf\b",
    r"\b__import__\s*\(",
]

# Questions that are plainly not about the dataset or the application. These
# are recognised without asking the model, so a joke gets the same short
# redirect every time.
_OFF_TOPIC_PATTERNS = [
    r"\btell\s+me\s+a\s+(?:joke|story|poem|riddle|pun)\b",
    r"\bwrite\s+(?:me\s+)?a\s+(?:joke|story|poem|song|riddle|essay|email|letter|blog\s+post)\b",
    r"\b(?:who|what)\s+(?:won|won\'t)\s+the\b",
    r"\b(?:president|prime\s+minister|election)\b.*\b(?:20\d\d)\b",
    r"\bwhat(?:'s| is) the (?:weather|news|price of bitcoin|exchange rate)\b",
    r"\b(?:recipe|how do i cook|make me a meal)\b",
    r"\b(?:tell me about|explain) (?:the history of|the history of the world)\b",
    r"\b(?:translate|summarize) .{0,40}\binto (?:french|spanish|german|japanese|chinese)\b",
    r"\bwho is (?:the|our) (?:president|prime minister|ceo of)\b",
    r"\b(?:give me|write me) (?:some )?jokes?\b",
]

# The assistant's scope, described for the classifier.
SCOPE_STATEMENT = """The assistant answers questions about ONE uploaded
dataset, and about itself and the application it belongs to. It is a data
analyst, not a general-purpose assistant.

In scope:
- figures, totals, averages, counts, comparisons, rankings, breakdowns and
  trends computed from the uploaded dataset's rows;
- the shape of the dataset: its columns, their types, their ranges, how many
  rows it has;
- the assistant and its application: which model it uses, what the
  application is built from, how the data is processed, and what the
  application can do.

Out of scope (redirected, not answered):
- the world outside the dataset: general knowledge, history, politics,
  science, current events, opinions, fiction;
- writing content that is not about the data: code, stories, poems, emails,
  marketing copy;
- anything about the user's files, other applications, the internet, or
  personal advice of any kind;
- doing anything other than analysing the dataset."""


def _matches(patterns: List[str], text: str) -> Optional[str]:
    """Return the name of the first pattern that matches, or None."""
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return pattern
    return None


def check_question(question: Any) -> str:
    """
    Apply the hard guardrails to a question.

    Args:
        question: The raw question from the user.

    Returns:
        The cleaned question, ready for the pipeline.

    Raises:
        GuardrailError: If the question is empty, too long, tries to
            redirect the assistant, or asks it to run code.
    """
    if not isinstance(question, str):
        raise GuardrailError(
            "The question must be sent as text.", code="not_text"
        )

    cleaned = question.strip()

    if not cleaned:
        raise GuardrailError(
            "Please ask a question about your data.", code="empty"
        )

    if len(cleaned) > MAX_QUESTION_CHARS:
        raise GuardrailError(
            f"That question is too long. Please keep it under "
            f"{MAX_QUESTION_CHARS} characters.",
            code="too_long",
        )

    if _matches(_INJECTION_PATTERNS, cleaned):
        raise GuardrailError(
            "I can only answer questions about your dataset, so I cannot act "
            "on instructions that redirect me elsewhere.",
            code="injection",
        )

    if _matches(_CODE_PATTERNS, cleaned):
        raise GuardrailError(
            "I analyse the uploaded dataset; I do not run code. Ask me a "
            "question about the data instead.",
            code="code_request",
        )

    return cleaned


def is_off_topic(question: str) -> bool:
    """Whether the question is plainly outside the assistant's purpose."""
    return _matches(_OFF_TOPIC_PATTERNS, question or "") is not None


# ---------------------------------------------------------------------------
# Layer 2: the topics a question about the assistant is asking for
# ---------------------------------------------------------------------------

# Each topic is recognised by what the question says, not by a single
# keyword. "Which model are you?" and "What model is configured in the
# running application?" both ask for the model; "What is your architecture?"
# asks about the application.
_TOPIC_PATTERNS: Dict[str, List[str]] = {
    TOPIC_MODEL: [
        r"\b(?:which|what)\s+model\b",
        r"\bmodel\s+(?:are|is)\s+(?:you|configured|being used|set)\b",
        r"\b(?:you|your)\s+model\b",
        r"\bmodel\s+(?:do you use|are you using|are you)\b",
        r"\bwhat\s+llm\b",
        r"\bwhich\s+llm\b",
        r"\b(?:you|your)\s+llm\b",
    ],
    TOPIC_PROVIDER: [
        r"\b(?:which|what)\s+provider\b",
        r"\bprovider\s+(?:do you use|are you using|are you|is configured)\b",
        r"\bwho\s+provides\s+(?:the\s+)?model\b",
        r"\bwho\s+hosts\s+(?:the\s+)?model\b",
    ],
    TOPIC_APP_ARCHITECTURE: [
        r"\b(?:your|the|this)\s+(?:application|app|system|backend|frontend)\s+architecture\b",
        r"\barchitecture\s+of\s+(?:the\s+)?(?:application|app|system|backend)\b",
        r"\bwhat\s+is\s+your\s+architecture\b",
        r"\b(?:your|the|this)\s+architecture\b",
        r"\b(?:explain|describe|outline)\s+(?:your|the|this)\s+architecture\b",
        r"\b(?:how are you built|how is this built|what is this application)\b",
        r"\btech\s*stack\b",
    ],
    TOPIC_MODEL_ARCHITECTURE: [
        r"\b(?:llm|model|language model)\s+architecture\b",
        r"\bunderlying\s+model.{0,20}architecture\b",
        r"\btransformer\s+architecture\b",
        r"\barchitecture\s+of\s+(?:the\s+)?(?:llm|model)\b",
    ],
    TOPIC_PIPELINE: [
        r"\bhow\s+(?:do you|does the app|does the application)\s+process\b",
        r"\bprocess\s+(?:my|the|your)\s+(?:uploaded\s+)?(?:dataset|data|file)\b",
        r"\bdata[- ]processing\b",
        r"\bquery\s+(?:execution|pipeline)\b",
        r"\bdata\s+pipeline\b",
        r"\bhow\s+(?:do you|does the app)\s+(?:answer|compute|calculate)\b",
        r"\bhow\s+(?:do you|does the app)\s+work\b",
    ],
    TOPIC_CAPABILITIES: [
        r"\bwhat\s+can\s+you\s+do\b",
        r"\bwhat\s+are\s+you\s+(?:able\s+)?to\s+do\b",
        r"\bwhat\s+(?:features|functions?|capabilities)\s+(?:do you have|does the app have|are there)\b",
        r"\bhow\s+can\s+(?:i|you)\s+use\s+(?:this|the app|you)\b",
        r"\bwhat\s+do\s+you\s+(?:support|offer)\b",
    ],
    TOPIC_CREATOR: [
        r"\bwho\s+(?:created|made|built|developed)\s+(?:you|this assistant|this app|the app)\b",
        r"\bwho\s+is\s+behind\s+(?:you|this assistant|this app|the app)\b",
    ],
}

# Words that mean the question is about the data rather than about the
# assistant. A question containing one of these is never treated as a
# question about the assistant, so a column that happens to be called
# "Model" still gets a computed answer.
_DATA_SIGNALS = [
    r"\b(?:total|sum|average|mean|median|max(?:imum)?|min(?:imum)?)\b",
    r"\bhow\s+many\b",
    r"\b(?:count|counts)\b",
    r"\b(?:top|bottom|best|worst|highest|lowest|rank|ranked|ranking)\b",
    r"\bby\s+\w+",
    r"\b(?:per|each|every)\b",
    r"\b(?:trend|trends|over\s+time|growth|monthly|weekly|daily|yearly|annual)\b",
    r"\b(?:filter|where|conditions?|greater|less|above|below|more than|less than)\b",
    r"\b(?:breakdown|split|group(?:ed)?\s+by|compare|comparison|difference|versus|vs)\b",
    r"\b(?:sales|revenue|profit|quantity|price|amount|total)\b",
    r"\b(?:column|columns|row|rows|field|fields)\b",
    r"\b(?:percentage|ratio|share|percent)\b",
    r"\b(?:list|show|give)\s+(?:me\s+)?(?:all|the|every)\b",
    r"\banalyz|analyz|analys|explore|investigate|explain\s+the\s+(?:trend|data|result)",
]

_DATASET_INFO_PATTERNS = [
    r"\bwhat\s+(?:data|dataset|file)\s+did\s+i\s+upload\b",
    r"\bwhich\s+(?:data|dataset|file)\s+did\s+i\s+upload\b",
    r"\bwhat(?:'s| is)\s+in\s+(?:my|the)\s+(?:uploaded\s+)?(?:dataset|file)\b",
    r"\bdescribe\s+(?:my|the)\s+(?:uploaded\s+)?dataset\b",
]


def detect_topics(question: str) -> Set[str]:
    """
    Which topics a question about the assistant is asking for.

    Only the topics the question actually names are returned, so the answer
    covers the question and nothing else.
    """
    text = (question or "").lower()
    found: Set[str] = set()

    for topic, patterns in _TOPIC_PATTERNS.items():
        if _matches(patterns, text):
            found.add(topic)

    return found


def is_data_question(question: str) -> bool:
    """Whether the question is asking for something computed from the data."""
    text = (question or "").lower()
    return _matches(_DATA_SIGNALS, text) is not None


def is_dataset_info_question(question: str) -> bool:
    """Whether the user asks which dataset is active or what it contains."""
    return _matches(_DATASET_INFO_PATTERNS, question or "") is not None


def detect_self_topics(question: str) -> Set[str]:
    """
    The topics of a question that is purely about the assistant.

    A question qualifies when it names one of the topics and shows no sign
    of asking for a figure from the data. Anything else is left to the
    classifier.
    """
    topics = detect_topics(question)
    if not topics:
        return set()
    if is_data_question(question):
        return set()
    return topics


# ---------------------------------------------------------------------------
# Layer 3: the verified facts
# ---------------------------------------------------------------------------

# The model name may be withheld by setting this to a false value. The
# provider name is a routing detail rather than a secret, and the API key
# and base URL are never exposable at all.
def _reveal_model_allowed() -> bool:
    return os.getenv("ASSISTANT_REVEAL_MODEL", "true").strip().lower() not in (
        "0", "false", "no", "off",
    )


def configured_model() -> str:
    """The configured model slug, or an empty string when it is unknown."""
    try:
        return (active_model() or "").strip()
    except Exception:  # noqa: BLE001 - a misconfigured provider must not crash an answer
        return ""


def configured_provider() -> str:
    """The configured provider name, or an empty string when it is unknown."""
    try:
        return (active_provider() or "").strip()
    except Exception:  # noqa: BLE001 - a misconfigured provider must not crash an answer
        return ""


def pipeline_steps() -> List[str]:
    """The data-processing and query-execution pipeline, as it really runs."""
    return [
        "Your upload is read into a dataframe and its schema is detected — "
        "the columns, their types and their ranges — and your rows are not "
        "sent to the model",
        "the model writes a declarative query plan saying which rows to "
        "keep, how to group them and what to compute",
        "the application runs that plan over your dataframe with its own "
        "code, under a fixed list of allowed operations",
        "the computed result is given back to the model to phrase, and the "
        "rows behind the answer are returned with it so you can check the "
        "work",
    ]


def verified_facts(topics: Set[str]) -> List[Dict[str, str]]:
    """
    The facts backing the answer, limited to the topics that were asked for.

    Only the model slug and the provider name are ever exposed. The API key,
    the base URL and the model's internal configuration are not.
    """
    facts: List[Dict[str, str]] = []

    if TOPIC_MODEL in topics:
        model = configured_model()
        facts.append({
            "label": "Model",
            "value": model if model else "not available in this configuration",
        })
    if TOPIC_PROVIDER in topics:
        provider = configured_provider()
        facts.append({
            "label": "Provider",
            "value": provider if provider else "not available in this configuration",
        })

    return facts


# ---------------------------------------------------------------------------
# The answers
# ---------------------------------------------------------------------------


def _model_answer() -> str:
    """One sentence naming the configured model."""
    model = configured_model()
    if not model:
        return (
            "I'm powered by the AI model configured for this application; its "
            "name isn't available to me from here."
        )
    if not _reveal_model_allowed():
        return "I'm powered by the AI model configured for this application."
    return f"I'm powered by the {model} model, configured for this application."


def _provider_answer() -> str:
    """One sentence naming the configured provider."""
    provider = configured_provider()
    if not provider:
        return (
            "This application's model is served through a configured "
            "provider, whose name isn't available to me from here."
        )
    return f"This application's model is served through {provider}."


def _app_architecture_answer() -> str:
    """A short description of the application's architecture."""
    return (
        "This application is a FastAPI backend with a React frontend: you "
        "upload a CSV or Excel file, and it detects the schema, then "
        "generates KPIs, charts, a dashboard, a written summary and a "
        "PowerPoint deck. The data-processing and query pipeline is a "
        "separate part of that — ask about it and I'll explain how a "
        "question becomes a number."
    )


def _model_architecture_answer() -> str:
    """An honest answer about the underlying model's internals."""
    return (
        "The model's internal architecture is the provider's implementation, "
        "not something this application configures, so I can't describe it "
        "from here. What this application does know is which model is "
        "configured."
    )


def _pipeline_answer() -> str:
    """A short description of the data-processing and query pipeline."""
    steps = "; ".join(pipeline_steps())
    return (
        "Your question is answered by computing over your data, not by "
        f"guessing. In short: {steps}."
    )


def _capabilities_answer() -> str:
    """A short description of what the application can do."""
    return (
        "I can help you analyze your uploaded data, explore trends, generate "
        "insights, create visualizations, answer data questions, and build "
        "editable PowerPoint reports."
    )


def _creator_answer() -> str:
    """Identify the application without inventing an individual or company."""
    return "I'm the AI assistant built into this application."


_TOPIC_ANSWERS = {
    TOPIC_MODEL: _model_answer,
    TOPIC_PROVIDER: _provider_answer,
    TOPIC_APP_ARCHITECTURE: _app_architecture_answer,
    TOPIC_MODEL_ARCHITECTURE: _model_architecture_answer,
    TOPIC_PIPELINE: _pipeline_answer,
    TOPIC_CAPABILITIES: _capabilities_answer,
    TOPIC_CREATOR: _creator_answer,
}

# The order topics are answered in, so a question that asks for two things
# reads in a sensible order.
_TOPIC_ORDER = [
    TOPIC_MODEL,
    TOPIC_PROVIDER,
    TOPIC_APP_ARCHITECTURE,
    TOPIC_MODEL_ARCHITECTURE,
    TOPIC_PIPELINE,
    TOPIC_CAPABILITIES,
    TOPIC_CREATOR,
]


def answer_about_self(topics: Set[str]) -> Dict[str, Any]:
    """
    Answer a question about the assistant, from the verified configuration.

    Only the topics that were asked for are answered, and each is answered
    within its own sentence budget. No model is involved, so the answer
    cannot be a guess and cannot drift into unrelated detail.
    """
    if not topics:
        topics = {TOPIC_MODEL}

    parts: List[str] = []
    for topic in _TOPIC_ORDER:
        if topic not in topics:
            continue
        answer = _TOPIC_ANSWERS[topic]()
        answer = apply_sentence_budget(answer, TOPIC_SENTENCE_BUDGET.get(topic, 2))
        if answer:
            parts.append(answer)

    return {
        "answer": " ".join(parts),
        "confidence": "high",
        "supporting_data": {
            "kind": "facts",
            "facts": verified_facts(topics),
        },
        "intent": INTENT_ABOUT,
    }


def answer_dataset_info(df: Any) -> Dict[str, Any]:
    """Describe the active dataset from the current dataframe only."""
    columns = [str(column) for column in getattr(df, "columns", [])]
    row_count, column_count = getattr(df, "shape", (0, len(columns)))
    column_text = ", ".join(columns) if columns else "no detected columns"
    return {
        "answer": (
            f"Your active dataset contains {row_count} rows and "
            f"{column_count} columns: {column_text}."
        ),
        "confidence": "high",
        "supporting_data": {
            "kind": "dataset",
            "row_count": int(row_count),
            "column_count": int(column_count),
            "columns": columns,
        },
        "intent": INTENT_DESCRIBE,
    }


def out_of_scope_answer() -> Dict[str, Any]:
    """
    The answer to a question outside the assistant's purpose.

    One sentence of redirect, in the user's language: no lectures, no
    listing of what the assistant can do.
    """
    return {
        "answer": (
            "I'm designed to help you analyze your uploaded data and "
            "generate reports. That question is outside my current scope."
        ),
        "confidence": "low",
        "supporting_data": {},
        "intent": INTENT_OUT_OF_SCOPE,
        "refused": True,
    }


# ---------------------------------------------------------------------------
# The final response policy
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, keeping the punctuation."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part for part in parts if part]


def apply_sentence_budget(text: str, budget: int) -> str:
    """Trim an answer to at most ``budget`` sentences."""
    sentences = _split_sentences(text)
    if budget <= 0 or len(sentences) <= budget:
        return text
    return " ".join(sentences[:budget])


def strip_unsolicited_sections(text: str) -> str:
    """
    Remove any section the model appended on its own initiative.

    The narration prompt asks for a plain answer, but a model can still add
    a "Verified configuration:" or "Scope:" block. Those are cut, so the
    answer is only what the question asked for.
    """
    lines = (text or "").splitlines()
    kept: List[str] = []

    for line in lines:
        stripped = line.strip().rstrip(":").strip().lower()
        if stripped in _UNSOLICITED_SECTION_HEADINGS and line.strip().endswith(":"):
            break
        kept.append(line)

    result = "\n".join(kept).strip()
    return result or (text or "").strip()


def apply_response_policy(answer: str, kind: str) -> str:
    """
    The last check on an answer before it is returned.

    ``kind`` is "self" for a question about the assistant, "off_topic" for
    a redirect, and "data" for an answer computed from the dataset.
    """
    cleaned = strip_unsolicited_sections(answer)

    if kind == "off_topic":
        return apply_sentence_budget(cleaned, 2)

    if kind == "self":
        return apply_sentence_budget(cleaned, 4)

    return cleaned
