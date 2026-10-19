"""The RAG pipeline: retrieve -> build grounded prompt -> generate -> cite."""

from __future__ import annotations

from typing import Any, Callable

from .config import Settings
from .llm import generate


SYSTEM_PROMPT = (
    "You are a document question-answering assistant. Answer ONLY using the numbered "
    "context passages provided. If the answer is not in the context, say you could not "
    "find it in the uploaded documents. Cite passages like [1], [2]. Be concise."
)
NO_ANSWER = "I couldn't find anything relevant to that in the uploaded documents."


def _location(hit: dict[str, Any]) -> str:
    source = str(hit.get("source", "unknown source"))
    page = hit.get("page")
    if not page:
        return source
    if isinstance(page, int):
        return f"{source}, page {page}"
    return f"{source}, section {page}"


def build_context(hits: list[dict]) -> str:
    parts = []
    for i, hit in enumerate(hits, start=1):
        parts.append(f"[{i}] ({_location(hit)})\n{hit.get('text', '')}")
    return "\n\n".join(parts)


def build_citations(hits: list[dict]) -> list[dict[str, Any]]:
    """Return JSON-friendly, grounded references for a generated answer."""
    citations: list[dict[str, Any]] = []
    for i, hit in enumerate(hits, start=1):
        score = hit.get("score")
        citation = {
            "index": i,
            "source": hit.get("source"),
            "page": hit.get("page"),
            "section": hit.get("section"),
            "chunk": hit.get("chunk"),
            "score": float(score) if score is not None else None,
            "text": hit.get("text", ""),
        }
        citations.append(citation)
    return citations


def _metrics(
    retrieved: list[dict],
    used: list[dict],
    settings: Settings,
    llm_called: bool,
) -> dict[str, Any]:
    scores = [float(hit["score"]) for hit in retrieved if hit.get("score") is not None]
    return {
        # The explicit names are useful to a React client; the *_count aliases
        # make the payload self-describing in logs and API consumers.
        "retrieved": len(retrieved),
        "retrieved_count": len(retrieved),
        "retrieved_chunks": len(retrieved),
        "used": len(used),
        "used_chunks": len(used),
        "context_chunks": len(used),
        "top_score": max(scores) if scores else None,
        "min_score": settings.min_score,
        "context_chars": sum(len(str(hit.get("text", ""))) for hit in used),
        "llm_called": llm_called,
    }


def answer(
    question: str,
    store: Any,
    s: Settings,
    history: list[dict] | None = None,
    llm_fn: Callable[..., str] = generate,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Return answer text plus source hits, citations, and retrieval metrics.

    Chunks scoring below ``MIN_SCORE`` are dropped; if nothing remains we skip
    the LLM entirely, which reduces hallucination on out-of-scope questions.
    ``sources`` optionally restricts retrieval to those documents.
    """
    retrieved = list(store.query(question, s.top_k, sources) or [])
    hits = [
        hit
        for hit in retrieved
        if hit.get("score") is not None and float(hit["score"]) >= s.min_score
    ]
    if not hits:
        return {
            "answer": NO_ANSWER,
            "sources": [],
            "citations": [],
            "metrics": _metrics(retrieved, [], s, llm_called=False),
        }

    messages = list(history or [])[-6:]  # last few turns for conversational follow-ups
    messages.append(
        {
            "role": "user",
            "content": f"Context:\n{build_context(hits)}\n\nQuestion: {question}",
        }
    )
    generated = llm_fn(SYSTEM_PROMPT, messages, s)
    return {
        "answer": generated,
        "sources": hits,
        "citations": build_citations(hits),
        "metrics": _metrics(retrieved, hits, s, llm_called=True),
    }
