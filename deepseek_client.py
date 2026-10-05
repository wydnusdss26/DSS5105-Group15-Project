"""Minimal official DeepSeek HTTPS client. Credentials never enter prompts or logs."""
import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"


class DeepSeekError(RuntimeError):
    pass


def network_enabled():
    # Explicit local consent persists across restarts; environment overrides it.
    override = os.environ.get("DEEPSEEK_NETWORK_ENABLED")
    if override is not None:
        return override.strip().lower() == "true"
    path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if path.exists():
        settings = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        return settings.get("DEEPSEEK_NETWORK_ENABLED", False) is True
    return False


def api_key():
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if value:
        return value
    path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if path.exists():
        return str(tomllib.loads(path.read_text(encoding="utf-8-sig")).get("DEEPSEEK_API_KEY", "")).strip()
    return ""


def complete(messages, tools=None):
    if not network_enabled():
        raise DeepSeekError("Online access is disabled. Only local data tools are available until sharing data with DeepSeek is enabled.")
    key = api_key()
    if not key:
        raise DeepSeekError("DEEPSEEK_API_KEY is not configured. The offline dashboard and tools remain available.")
    payload = {"model": MODEL, "messages": messages, "max_tokens": 2200,
               "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}}
    if tools:
        payload["tools"] = tools
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        explanations = {401: "API key authentication failed", 402: "Insufficient API balance", 429: "API rate limit reached. Please try again later"}
        raise DeepSeekError(explanations.get(exc.code, f"DeepSeek API is unavailable (HTTP {exc.code})")) from None
    except (OSError, ValueError, TimeoutError):
        raise DeepSeekError("DeepSeek timed out or returned an invalid response. Please try again. Saved data is unaffected.") from None
    choices = result.get("choices", [])
    if not choices or choices[0].get("finish_reason") not in ["stop", "tool_calls"]:
        raise DeepSeekError("The model response was incomplete. Please narrow your question and try again.")
    return choices[0]["message"], result.get("usage", {})
