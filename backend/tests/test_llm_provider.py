"""Checks for the LLM provider client (OpenRouter via the OpenAI SDK)."""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import src.core.llm as llm  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, recorder, reply):
        self._recorder = recorder
        self._reply = reply

    def create(self, **kwargs):
        self._recorder["model"] = kwargs.get("model")
        self._recorder["messages"] = kwargs.get("messages")
        self._recorder["max_tokens"] = kwargs.get("max_tokens")
        if isinstance(self._reply, Exception):
            raise self._reply
        return _FakeResponse(self._reply)


class _FakeClient:
    def __init__(self, base_url, api_key, recorder, reply):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions(recorder, reply)


class _FakeError(Exception):
    """Stands in for an SDK error carrying a status code and a response."""

    def __init__(self, message, status_code=None, payload=None, headers=None):
        super().__init__(message)
        self.status_code = status_code

        class _Resp:
            def __init__(self):
                self._payload = payload or {}
                self.headers = headers or {}

            def json(self):
                return self._payload

        self.response = _Resp()


def _all_setting_keys():
    keys = []
    for provider in llm._PROVIDERS.values():
        keys += list(provider.api_key_keys) + list(provider.base_url_keys) + list(provider.model_keys)
    return sorted(set(keys))


def _clear_env():
    for key in _all_setting_keys() + ["LLM_PROVIDER", "LLM_PROVIDER_NAME", "AI_PROVIDER"]:
        os.environ.pop(key, None)
    llm._discovered = {}


def main():
    print("\n[1] Providers use the OpenAI-compatible API")
    source = (BASE_DIR / "src" / "core" / "llm.py").read_text(encoding="utf-8")
    check("Does not import google.generativeai", "google.generativeai" not in source)
    check("Supports Gemini configuration", "GEMINI_API_KEY" in source)
    check("Uses the OpenAI SDK", "from openai import OpenAI" in source)
    check("Uses the chat completions API", "chat.completions.create" in source)
    check("Supports OpenRouter", "openrouter" in source)
    check("Supports Gemini", "gemini" in source)

    print("\n[2] Configuration is read from the environment")
    saved = {k: os.environ.get(k) for k in _all_setting_keys()}
    saved_discovered = llm._discovered
    original_build = llm._build_client
    try:
        _clear_env()
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_BASE_URL"] = "https://example.test/api/v1"
        os.environ["OPENROUTER_MODEL"] = "vendor/some-model"
        recorder = {}

        def fake_build(reply):
            def _inner(provider=None):
                provider = provider or llm._select_provider()
                return _FakeClient(
                    llm._lookup(provider, "base_url"),
                    llm._lookup(provider, "api_key"),
                    recorder,
                    reply,
                )
            return _inner

        llm._build_client = fake_build("  Hello from the model.  ")
        check("Returns the model's text, stripped",
              llm.generate_response("hi") == "Hello from the model.")
        check("Sends the configured model", recorder.get("model") == "vendor/some-model")
        check("Sends the prompt as a user message",
              recorder.get("messages") == [{"role": "user", "content": "hi"}])
        check("Sends no max_tokens by default", recorder.get("max_tokens") is None)

        llm._build_client = fake_build("ok")
        llm.generate_response("hi", max_tokens=1500)
        check("Sends max_tokens when asked", recorder.get("max_tokens") == 1500)

        print("\n[3] The provider is selected")
        check("OpenRouter is selected when it is configured",
              llm._select_provider().name == "openrouter")

        os.environ["LLM_PROVIDER"] = "openrouter"
        check("An explicit LLM_PROVIDER wins",
              llm._select_provider().name == "openrouter")
        os.environ["LLM_PROVIDER"] = "nonsense"
        try:
            llm._select_provider()
            check("An unknown LLM_PROVIDER is rejected", False, "no error raised")
        except llm.LLMConfigError:
            check("An unknown LLM_PROVIDER is rejected", True)

        print("\n[4] Failures are surfaced as LLMError")
        _clear_env()
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        llm._build_client = fake_build(RuntimeError("network down"))
        try:
            llm.generate_response("hi")
            check("Raises on a provider failure", False, "no error raised")
        except llm.LLMError:
            check("Raises on a provider failure", True)
        except Exception as exc:  # noqa: BLE001
            check("Raises on a provider failure", False, type(exc).__name__)

        llm._build_client = fake_build("")
        try:
            llm.generate_response("hi")
            check("Raises on an empty response", False, "no error raised")
        except llm.LLMError:
            check("Raises on an empty response", True)

        print("\n[5] Input validation")
        try:
            llm.generate_response("   ")
            check("Rejects an empty prompt", False, "no error raised")
        except ValueError:
            check("Rejects an empty prompt", True)

        print("\n[6] A missing key is a configuration error")
        _clear_env()
        llm._build_client = original_build
        try:
            llm.generate_response("hi")
            check("Raises when no API key is configured", False, "no error raised")
        except llm.LLMConfigError:
            check("Raises when no API key is configured", True)
        except llm.LLMError:
            check("Raises when no API key is configured", True)
        except Exception as exc:  # noqa: BLE001
            check("Raises when no API key is configured", False, type(exc).__name__)

        print("\n[7] A rate limit is reported with the quota details")
        _clear_env()
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_MODEL"] = "vendor/some-model"
        llm._build_client = fake_build(_FakeError(
            "Error code: 429 - rate limit",
            status_code=429,
            payload={"error": {"metadata": {
                "headers": {"X-RateLimit-Limit": "50",
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": "1792540800000"},
                "limit_source": "openrouter_free_tier_daily"}}},
            headers={"x-ratelimit-limit-requests": "50",
                     "x-ratelimit-remaining-requests": "0"},
        ))
        try:
            llm.generate_response("hi")
            check("Raises on a rate limit", False, "no error raised")
        except llm.LLMRateLimitError as exc:
            check("Raises on a rate limit", True)
            check("Carries the limit", exc.limit == 50, str(exc.limit))
            check("Carries the remaining count", exc.remaining == 0, str(exc.remaining))
            check("Carries the reset time", bool(exc.reset_at), str(exc.reset_at))
            check("Carries the limit source",
                  exc.source == "openrouter_free_tier_daily", str(exc.source))
        except Exception as exc:  # noqa: BLE001
            check("Raises on a rate limit", False, type(exc).__name__)

    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        llm._discovered = saved_discovered
        llm._build_client = original_build

    print("\n[8] Settings can be discovered from the .env file")
    check("Classifies an OpenRouter base url", llm._classify("OPENROUTER_BASE_URL") == ("openrouter", "base_url"))
    check("Classifies an OpenRouter api key", llm._classify("OPENROUTER_API_KEY") == ("openrouter", "api_key"))
    check("Classifies an OpenRouter model", llm._classify("OPENROUTER_MODEL") == ("openrouter", "model"))
    check("Classifies an alternative spelling",
          llm._classify("OPEN_ROUTER_API_KEY") == ("openrouter", "api_key"))
    check("Classifies a Gemini api key", llm._classify("GEMINI_API_KEY") == ("gemini", "api_key"))
    check("Classifies a Gemini model", llm._classify("GEMINI_MODEL") == ("gemini", "model"))
    check("Ignores an unrelated variable", llm._classify("DATABASE_URL") is None)
    check("Ignores a Groq variable", llm._classify("GROQ_API_KEY") is None)

    print("\n[9] The client does not retry a failed request")
    check("Retries are disabled", "max_retries=0" in source)

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All LLM provider checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
