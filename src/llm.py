"""Thin LLM wrapper: local Ollama (default), Gemini, or Anthropic (optional)."""
import os

import requests

from .config import Settings


OLLAMA_OFFLINE_HINT = (
    "Ollama is not reachable. Start Ollama and pull the model, "
    "e.g. `ollama serve` then `ollama pull llama3.2:3b`, "
    "or set LLM_PROVIDER=anthropic with ANTHROPIC_API_KEY."
)


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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{s.llm_model}:generateContent"
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
    try:
        resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
    except requests.exceptions.ConnectionError as exc:
        raise ConnectionError(
            "Could not reach the Gemini API. Check your network connection and retry."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise TimeoutError("The Gemini API timed out after 120s. Please retry.") from exc
    if resp.status_code in (400, 401, 403, 404, 429):
        detail = resp.text[:300]
        try:
            error = resp.json().get("error", {})
            detail = error.get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"Gemini API error (HTTP {resp.status_code}): {detail}")
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Gemini API error (HTTP {resp.status_code}).") from exc
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
