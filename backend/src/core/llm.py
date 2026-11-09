"""LLM client wrapper for AI-driven features."""

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from dotenv import dotenv_values, load_dotenv

logger = logging.getLogger(__name__)

# Load .env from the working directory first, then from the backend root, so
# the app behaves the same whether it is started from the repo root or from
# inside backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILES = [p for p in (Path.cwd() / ".env", _BACKEND_ROOT / ".env", _BACKEND_ROOT.parent / ".env") if p.is_file()]
for _candidate in _ENV_FILES:
    load_dotenv(_candidate, override=False)


class _Provider:
    """One OpenAI-compatible provider and how its settings are named."""

    def __init__(
        self,
        name: str,
        base_url_keys: Tuple[str, ...],
        api_key_keys: Tuple[str, ...],
        model_keys: Tuple[str, ...],
        default_base_url: str,
        default_model: str,
        markers: Tuple[str, ...],
    ):
        self.name = name
        self.base_url_keys = base_url_keys
        self.api_key_keys = api_key_keys
        self.model_keys = model_keys
        self.default_base_url = default_base_url
        self.default_model = default_model
        self.markers = markers


_PROVIDERS: Dict[str, _Provider] = {
    "openrouter": _Provider(
        name="openrouter",
        base_url_keys=("OPENROUTER_BASE_URL", "OPENROUTER_URL", "OPENROUTER_API_BASE", "OPENROUTER_API_URL"),
        api_key_keys=("OPENROUTER_API_KEY", "OPENROUTER_KEY", "OPENROUTER_TOKEN"),
        model_keys=("OPENROUTER_MODEL", "OPENROUTER_MODEL_ID", "OPENROUTER_MODEL_NAME"),
        default_base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        markers=("openrouter", "open_router"),
    ),
    "gemini": _Provider(
        name="gemini",
        base_url_keys=("GEMINI_BASE_URL", "GEMINI_API_BASE", "GEMINI_API_URL"),
        api_key_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        model_keys=("GEMINI_MODEL", "GEMINI_MODEL_ID", "GEMINI_MODEL_NAME"),
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
        markers=("gemini", "google"),
    ),
}

# Name fragments used to auto-discover a setting when it is spelled
# differently (e.g. "OPEN_ROUTER_API_KEY").
_BASE_URL_MARKERS = ("base_url", "baseurl", "api_base", "apibase", "api_url", "apiurl", "url")
_API_KEY_MARKERS = ("api_key", "apikey", "key", "token", "secret")
_MODEL_MARKERS = ("model",)

# Cached auto-discovered settings, so the .env file is parsed once.
_discovered: Optional[Dict[str, Dict[str, str]]] = None


def _read_env_files() -> Dict[str, str]:
    """Read every .env file's variables into a single dict (later files win)."""
    values: Dict[str, str] = {}
    for path in _ENV_FILES:
        try:
            values.update({k: v for k, v in dotenv_values(path).items() if v})
        except Exception:  # noqa: BLE001 - a malformed .env must not break the app
            logger.warning("Could not read %s", path, exc_info=True)
    return values


def _classify(name: str) -> Optional[Tuple[str, str]]:
    """
    Classify an environment variable name.

    Returns a (provider, kind) pair — e.g. ("groq", "api_key") — or None when
    the name is not one of ours. The kind is "base_url", "api_key" or "model".
    """
    lowered = name.lower()
    for provider in _PROVIDERS.values():
        if not any(marker in lowered for marker in provider.markers):
            continue
        if any(marker in lowered for marker in _MODEL_MARKERS):
            return provider.name, "model"
        if any(marker in lowered for marker in _BASE_URL_MARKERS):
            return provider.name, "base_url"
        if any(marker in lowered for marker in _API_KEY_MARKERS):
            return provider.name, "api_key"
    return None


def _discover_settings() -> Dict[str, Dict[str, str]]:
    """
    Find each provider's settings in .env by inspecting variable names.

    The .env file may spell the variables in several ways; rather than
    guessing, the names are read and classified. Values are never logged.
    """
    global _discovered
    if _discovered is not None:
        return _discovered

    found: Dict[str, Dict[str, str]] = {name: {} for name in _PROVIDERS}
    for name, value in _read_env_files().items():
        classified = _classify(name)
        if classified and value.strip():
            provider, kind = classified
            found[provider].setdefault(kind, value.strip())

    _discovered = found
    return found


def _first_env(keys) -> str:
    """Return the first non-empty environment variable among the given names."""
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return ""


def _lookup(provider: _Provider, kind: str) -> str:
    """Resolve one of a provider's settings from the environment, then .env."""
    if kind == "base_url":
        keys = provider.base_url_keys
    elif kind == "api_key":
        keys = provider.api_key_keys
    else:
        keys = provider.model_keys

    value = _first_env(keys)
    if value:
        return value
    return _discover_settings().get(provider.name, {}).get(kind, "")


def _select_provider() -> _Provider:
    """
    Choose the provider to talk to.

    An explicit LLM_PROVIDER setting selects the configured provider. Without
    one, Gemini is preferred when its key is configured, otherwise OpenRouter
    is used for backwards compatibility.
    """
    explicit = _first_env(("LLM_PROVIDER", "LLM_PROVIDER_NAME", "AI_PROVIDER")).lower()
    if explicit:
        provider = _PROVIDERS.get(explicit)
        if provider is None:
            raise LLMConfigError(
                f"Unknown LLM_PROVIDER {explicit!r}. Choose one of: "
                + ", ".join(_PROVIDERS)
                + "."
            )
        return provider

    if _lookup(_PROVIDERS["gemini"], "api_key"):
        return _PROVIDERS["gemini"]
    return _PROVIDERS["openrouter"]


class LLMError(Exception):
    """Raised when the LLM provider fails to produce a response."""


def active_model() -> str:
    """
    The model slug the app is currently talking to.

    Returned so the assistant can say which model answered, rather than
    claiming a model it does not know.
    """
    provider = _select_provider()
    return _lookup(provider, "model") or provider.default_model


def active_provider() -> str:
    """The name of the provider the app is currently talking to."""
    return _select_provider().name


class LLMConfigError(LLMError):
    """Raised when the LLM provider is misconfigured (e.g. missing API key)."""


class LLMRateLimitError(LLMError):
    """
    Raised when the provider refuses the request because a quota is exhausted.

    Carries whatever the provider reported about the limit, so the caller can
    tell the user when the quota resets instead of failing silently.
    """

    def __init__(self, message: str, limit: Optional[int] = None,
                 remaining: Optional[int] = None, reset_at: Optional[str] = None,
                 source: Optional[str] = None):
        super().__init__(message)
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at
        self.source = source


def _build_client(provider: Optional[_Provider] = None):
    """Create an OpenAI client pointed at the configured provider's endpoint."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMConfigError("The 'openai' package is not installed.") from exc

    provider = provider or _select_provider()
    base_url = _lookup(provider, "base_url") or provider.default_base_url
    api_key = _lookup(provider, "api_key")
    if not api_key:
        raise LLMConfigError(
            f"No API key found for {provider.name}. Set one of: "
            + ", ".join(provider.api_key_keys) + " in .env."
        )

    # Retries are disabled deliberately. The SDK retries a 429 twice by
    # default, and a quota that is exhausted for the day will not clear
    # within its backoff window — so each failed call would spend three
    # requests instead of one. Transient failures are handled by the
    # caller falling back to the deterministic templates.
    return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)


def _rate_limit_details(error: Exception) -> Dict[str, object]:
    """
    Pull whatever the provider reported about the quota out of an error.

    OpenRouter nests the limit headers under error.metadata.headers; Groq
    puts them in the HTTP response headers. Both are read.
    """
    details: Dict[str, object] = {}

    response = getattr(error, "response", None)
    if response is not None:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - the body may not be JSON
            payload = {}

        metadata = (payload or {}).get("error", {}).get("metadata", {}) or {}
        headers = metadata.get("headers", {}) or {}
        details["source"] = metadata.get("limit_source")
        details["remedy"] = metadata.get("remedy_hint")

        for name, value in (getattr(response, "headers", None) or {}).items():
            lowered = name.lower()
            if lowered == "x-ratelimit-limit-requests":
                headers.setdefault("X-RateLimit-Limit", value)
            elif lowered == "x-ratelimit-remaining-requests":
                headers.setdefault("X-RateLimit-Remaining", value)
            elif lowered == "x-ratelimit-reset-requests":
                headers.setdefault("X-RateLimit-Reset", value)

        limit = headers.get("X-RateLimit-Limit")
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")

        try:
            details["limit"] = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            details["limit"] = None
        try:
            details["remaining"] = int(remaining) if remaining is not None else None
        except (TypeError, ValueError):
            details["remaining"] = None

        if reset is not None:
            try:
                from datetime import datetime, timezone

                seconds = int(reset) / 1000
                details["reset_at"] = datetime.fromtimestamp(
                    seconds, timezone.utc
                ).isoformat()
            except (TypeError, ValueError, OSError):
                details["reset_at"] = None

    return details


def generate_response(prompt: str, max_tokens: Optional[int] = None) -> str:
    """
    Generate a text response from the configured provider.

    Args:
        prompt: The prompt to send.
        max_tokens: Cap on the number of tokens to generate. This is set
            explicitly because providers differ: OpenRouter reserves the
            model's whole context window against the account's credit
            balance, and a request without a cap is rejected when the
            balance cannot cover it. Leaving it unset keeps the provider's
            own default.

    Raises:
        ValueError: If the prompt is empty.
        LLMConfigError: If the provider is misconfigured or the SDK is missing.
        LLMRateLimitError: If the provider's quota is exhausted.
        LLMError: If the request fails or returns an empty response.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")

    provider = _select_provider()
    client = _build_client(provider)
    model_name = _lookup(provider, "model") or provider.default_model

    logger.info(
        "Generating LLM response using %s model '%s'.", provider.name, model_name
    )

    request: Dict[str, object] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
    }
    if max_tokens is not None:
        request["max_tokens"] = max_tokens

    try:
        response = client.chat.completions.create(**request)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any SDK/network failure uniformly
        status = getattr(exc, "status_code", None)
        if status == 429:
            details = _rate_limit_details(exc)
            message = str(exc)
            logger.warning(
                "%s rate limit reached (limit=%s remaining=%s reset=%s).",
                provider.name, details.get("limit"), details.get("remaining"),
                details.get("reset_at"),
            )
            raise LLMRateLimitError(
                f"{provider.name} rate limit reached: {message}",
                limit=details.get("limit"),
                remaining=details.get("remaining"),
                reset_at=details.get("reset_at"),
                source=details.get("source"),
            ) from exc
        logger.exception("%s request failed.", provider.name)
        raise LLMError(f"{provider.name} request failed: {exc}") from exc

    try:
        text = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError) as exc:
        raise LLMError(f"{provider.name} returned an unexpected response shape.") from exc

    if not text or not text.strip():
        raise LLMError(f"{provider.name} returned an empty response.")

    return text.strip()
