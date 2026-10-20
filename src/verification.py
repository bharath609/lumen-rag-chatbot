"""Post-answer trust layer: claim-level faithfulness checks and follow-ups.

Research-grounded design (RAGAS-style claim decomposition with an LLM judge):
the generated answer is split into factual claims and each claim is checked
for entailment against the retrieved passages. Unsupported claims are surfaced
to the user instead of being silently presented as fact. The whole layer is
fail-open: if the verification call itself errors, the answer is unaffected.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_VERIFY_SYSTEM = (
    "You are a strict fact-checker for a retrieval-augmented assistant. You get "
    "numbered document passages and an ANSWER that claims to be based only on "
    "them. Split the ANSWER into its individual factual claims. For each claim, "
    "decide whether the passages entailed-by- alone support it. A claim that "
    "needs outside knowledge, rounding, or inference beyond the passages is "
    "unsupported. Answer ONLY with JSON in this exact shape: "
    '{"supported": true, "unsupported": ["short claim text"]}. '
    "supported is false only when at least one claim is unsupported; list at "
    "most 3 unsupported claims, each under 15 words."
)

_FOLLOWUP_SYSTEM = (
    "Given a question and an answer about a user's documents, suggest exactly 3 "
    "short follow-up questions a curious reader would ask next. They must be "
    "about information plausibly contained in the same documents, and must "
    "never be answerable from your own world knowledge. Answer ONLY with JSON: "
    '{"questions": ["...?", "...?", "...?"]} with no numbering.'
)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "1").strip().lower() not in {"0", "false", "no", "off"}


def _first_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _passages_text(hits: list[dict], limit: int = 6000) -> str:
    """Numbered context identical in style to the grounded prompt."""
    parts: list[str] = []
    used = 0
    for i, hit in enumerate(hits, start=1):
        block = f"[{i}] ({hit.get('source', '?')})\n{hit.get('text', '')}"
        if used + len(block) > limit and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def verify_answer(
    answer_text: str, hits: list[dict], s: Any, generate: Any
) -> dict[str, Any]:
    """Classify the answer's claims against the cited passages.

    Returns {"status": "supported"|"flagged"|"skipped", "unsupported": [...]}.
    """
    if not _env_flag("VERIFY_ANSWERS") or not answer_text or not hits:
        return {"status": "skipped", "unsupported": []}
    user_text = (
        f"DOCUMENT PASSAGES:\n{_passages_text(hits)}\n\nANSWER:\n{answer_text}"
    )
    try:
        raw = generate(_VERIFY_SYSTEM, [{"role": "user", "content": user_text}], s)
    except Exception:
        return {"status": "skipped", "unsupported": []}
    payload = _first_json(str(raw))
    if payload is None or "supported" not in payload:
        return {"status": "skipped", "unsupported": []}
    unsupported = [
        str(item).strip()
        for item in (payload.get("unsupported") or [])
        if str(item).strip()
    ][:3]
    if payload.get("supported") is True or not unsupported:
        return {"status": "supported", "unsupported": []}
    return {"status": "flagged", "unsupported": unsupported}


def suggest_followups(
    question: str, answer_text: str, hits: list[dict], s: Any, generate: Any
) -> list[str]:
    """Three grounded next questions after an answer (empty list on failure)."""
    if not _env_flag("SUGGEST_FOLLOWUPS") or not answer_text or not hits:
        return []
    user_text = (
        f"Documents:\n{_passages_text(hits, 3000)}\n\n"
        f"Question asked: {question}\nAnswer given: {answer_text[:2000]}"
    )
    try:
        raw = generate(_FOLLOWUP_SYSTEM, [{"role": "user", "content": user_text}], s)
    except Exception:
        return []
    payload = _first_json(str(raw))
    if not payload or not isinstance(payload.get("questions"), list):
        return []
    return [str(q).strip() for q in payload["questions"] if str(q).strip()][:3]
