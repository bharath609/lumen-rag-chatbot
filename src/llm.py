"""Thin LLM wrapper: local Ollama (default), Gemini, or Anthropic (optional)."""
import os
import random
import time

import requests

from .config import Settings


OLLAMA_OFFLINE_HINT = (
    "Ollama is not reachable. Start Ollama and pull the model, "
    "e.g. `ollama serve` then `ollama pull llama3.2:3b`, "
    "or set LLM_PROVIDER=anthropic with ANTHROPIC_API_KEY."
)

GEMINI_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
GEMINI_FALLBACK_STATUS_CODES = {500, 502, 503, 504}


def generate(system: str, messages: list[dict], s: Settings) -> str:
    if s.llm_provider == "ollama":
        try:
            resp = requests.post(
                f"{s.ollama_host}/api/chat",
                json={
                    "model": s.llm_model,
                    "messages": [{"role": "system", "content": system}, *messages],
                    "stream": False,
                },
                timeout=300,
            )
        except requests.exceptions.ConnectionError as exc:
            raise ConnectionError(
                f"{OLLAMA_OFFLINE_HINT} (tried {s.ollama_host})"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(
                f"Ollama timed out after 300s at {s.ollama_host}. Try a smaller model or fewer chunks."
            ) from exc
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            detail = ""
            try:
                detail = f" — {resp.json().get('error', '')}".rstrip(" — ")
            except Exception:
                detail = f" — {resp.text[:200]}" if resp.text else ""
            raise RuntimeError(
                f"Ollama returned HTTP {resp.status_code}{detail}. "
                f"Is model '{s.llm_model}' pulled? Run `ollama pull {s.llm_model}`."
            ) from exc
        try:
            return resp.json()["message"]["content"].strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Ollama returned an unexpected response shape at {s.ollama_host}."
            ) from exc

    if s.llm_provider == "anthropic":
        import anthropic  # reads ANTHROPIC_API_KEY from the environment

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=s.llm_model, max_tokens=1000, system=system, messages=messages
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    if s.llm_provider == "gemini":
        return _generate_gemini(system, messages, s)

    raise ValueError(f"Unknown LLM_PROVIDER: {s.llm_provider}")


def _generate_gemini(system: str, messages: list[dict], s: Settings) -> str:
    """Answer via the Google Gemini API (free tier friendly, no extra deps)."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and set GEMINI_API_KEY."
        )
    contents = []
    for item in messages:
        role = "model" if item.get("role") == "assistant" else "user"
        text = item.get("content", "")
        if isinstance(text, str) and text.strip():
            contents.append({"role": role, "parts": [{"text": text}]})
    body: dict = {
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    if isinstance(system, str) and system.strip():
        body["system_instruction"] = {"parts": [{"text": system}]}
    max_retries = _gemini_int_env("GEMINI_MAX_RETRIES", 2, minimum=0)
    retry_base_seconds = _gemini_float_env("GEMINI_RETRY_BASE_SECONDS", 1.0, minimum=0.0)
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()
    models = [s.llm_model]
    if fallback_model and fallback_model != s.llm_model:
        models.append(fallback_model)

    last_retryable: tuple[int, str] | None = None
    for model_index, model in enumerate(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
            except requests.exceptions.ConnectionError as exc:
                if attempt < max_retries:
                    _sleep_before_gemini_retry(retry_base_seconds, attempt)
                    continue
                raise ConnectionError(
                    "Could not reach the Gemini API. Check your network connection and retry."
                ) from exc
            except requests.exceptions.Timeout as exc:
                if attempt < max_retries:
                    _sleep_before_gemini_retry(retry_base_seconds, attempt)
                    continue
                raise TimeoutError("The Gemini API timed out after 120s. Please retry.") from exc

            if resp.status_code in GEMINI_RETRYABLE_STATUS_CODES:
                detail = _gemini_error_detail(resp)
                last_retryable = (resp.status_code, detail)
                if attempt < max_retries:
                    _sleep_before_gemini_retry(retry_base_seconds, attempt)
                    continue
                if (
                    model_index + 1 < len(models)
                    and resp.status_code in GEMINI_FALLBACK_STATUS_CODES
                ):
                    break
                attempts = max_retries + 1
                raise RuntimeError(
                    f"Gemini API is temporarily unavailable (HTTP {resp.status_code}) "
                    f"after {attempts} attempts: {detail}"
                )

            if resp.status_code in (400, 401, 403, 404):
                detail = _gemini_error_detail(resp)
                raise RuntimeError(f"Gemini API error (HTTP {resp.status_code}): {detail}")
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                raise RuntimeError(f"Gemini API error (HTTP {resp.status_code}).") from exc
            return _parse_gemini_response(resp)

    if last_retryable is not None:  # defensive guard for an exhausted fallback loop
        status, detail = last_retryable
        raise RuntimeError(
            f"Gemini API is temporarily unavailable (HTTP {status}). Please retry shortly: {detail}"
        )
    raise RuntimeError("Gemini API did not return an answer.")


def _gemini_int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _gemini_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _sleep_before_gemini_retry(base_seconds: float, attempt: int) -> None:
    """Use bounded exponential backoff with jitter for transient API failures."""
    delay = base_seconds * (2**attempt) + random.uniform(0.0, 0.25)
    time.sleep(delay)


def _gemini_error_detail(resp: requests.Response) -> str:
    detail = (resp.text or "").strip()[:300]
    try:
        error = resp.json().get("error", {})
        if isinstance(error, dict) and error.get("message"):
            detail = str(error["message"])
    except (TypeError, ValueError):
        pass
    return detail or "No additional error details were returned."


def _parse_gemini_response(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("Gemini returned a non-JSON response.") from exc
    if isinstance(data.get("promptFeedback", {}).get("blockReason"), str):
        raise RuntimeError(
            f"Gemini declined to answer (blocked: {data['promptFeedback']['blockReason']}). "
            "Try rephrasing the question."
        )
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini returned an unexpected response shape.") from exc
    if not text:
        raise RuntimeError("Gemini returned an empty answer. Please retry.")
    return text
