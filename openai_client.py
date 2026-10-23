"""OpenAI Responses transport; credentials stay out of prompts and error messages."""
import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "gpt-6.1-sol"
MODEL_LABEL = "GPT-6.1 Sol"
ENDPOINT = "https://api.openai.com/v1/responses"


class ModelError(RuntimeError):
    pass


def local_settings():
    path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        # Do not expose private configuration contents through a parser traceback.
        return {}


def network_enabled():
    override = os.environ.get("OPENAI_NETWORK_ENABLED")
    if override is not None:
        return override.strip().lower() == "true"
    return local_settings().get("OPENAI_NETWORK_ENABLED", False) is True


def api_key():
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    return value or str(local_settings().get("OPENAI_API_KEY", "")).strip()


def response_input(messages):
    """Adapt internal chat turns while retaining encrypted reasoning across tool rounds."""
    items = []
    for message in messages:
        if message.get("_response_output"):
            items.extend(message["_response_output"])
        elif message["role"] == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": message["content"]})
        else:
            content = message.get("content")
            if content:
                role = "developer" if message["role"] == "system" else message["role"]
                items.append({"role": role, "content": content})
            for call in message.get("tool_calls", []):
                items.append({"type": "function_call", "call_id": call["id"],
                              "name": call["function"]["name"], "arguments": call["function"]["arguments"]})
    return items


def complete(messages, tools=None):
    if not network_enabled():
        raise ModelError("Online access is disabled. Local data tools remain available until sharing data with OpenAI is enabled.")
    key = api_key()
    if not key:
        raise ModelError("OPENAI_API_KEY is not configured. The offline dashboard and tools remain available.")
    payload = {"model": MODEL, "input": response_input(messages), "max_output_tokens": 6000,
               "reasoning": {"effort": "low"}, "store": False,
               "include": ["reasoning.encrypted_content"], "text": {"format": {"type": "json_object"}}}
    if tools:
        payload["tools"] = [{"type": "function", **tool["function"], "strict": False} for tool in tools]
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                error = json.load(exc)
                detail = error.get("error", {}) if isinstance(error, dict) else {}
                code = detail.get("code")
                error_type = detail.get("type")
            except (OSError, ValueError, AttributeError):
                code, error_type = None, None
            if code == "credit_balance_exhausted":
                raise ModelError("OpenAI API credit balance is exhausted. Add API credits, then retry.") from None
            if code in {"project_spend_limit_exceeded", "organization_spend_limit_exceeded", "organization_usage_limit_exceeded"}:
                raise ModelError("OpenAI API spending or usage limit reached. Check the project and organization limits, then retry.") from None
            if error_type == "insufficient_quota" or code in {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active"}:
                raise ModelError("OpenAI API quota is unavailable. Add API credits or check this project's billing/spending limit, then retry.") from None
        explanations = {400: "OpenAI rejected the request configuration (HTTP 400).",
                        401: "OpenAI API key authentication failed.",
                        403: "This OpenAI project does not have permission for the request.",
                        404: f"The OpenAI model {MODEL} is unavailable to this project.",
                        429: "OpenAI quota or rate limit reached. Check API billing and limits, then try again."}
        raise ModelError(explanations.get(exc.code, f"OpenAI API is unavailable (HTTP {exc.code}).")) from None
    except (OSError, ValueError, TimeoutError):
        raise ModelError("OpenAI timed out or returned an invalid response. Saved data is unaffected.") from None
    if not isinstance(result, dict) or result.get("status") != "completed":
        raise ModelError("The model response was incomplete. Please narrow your question and try again.")
    output = result.get("output", [])
    if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
        raise ModelError("OpenAI returned an invalid response structure.")
    calls, text = [], []
    for item in output:
        if item.get("type") == "function_call":
            if not all(isinstance(item.get(field), str) for field in ("call_id", "name", "arguments")):
                raise ModelError("OpenAI returned an invalid tool call.")
            calls.append({"id": item["call_id"], "type": "function",
                          "function": {"name": item["name"], "arguments": item["arguments"]}})
        elif item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise ModelError("The model could not answer this request. Please rephrase it.")
                if part.get("type") == "output_text":
                    text.append(part.get("text", ""))
    if not calls and not text:
        raise ModelError("OpenAI returned no usable answer. Please try again.")
    message = {"role": "assistant", "content": "".join(text) or None, "_response_output": output}
    if calls:
        message["tool_calls"] = calls
    usage = result.get("usage") or {}
    return message, {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0)}
