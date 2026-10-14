"""Persistent ChromaDB vector store with lazy sentence-transformer embeddings."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class VectorStore:
    """A small persistent vector store used by Streamlit, the CLI, and the API.

    Chroma is opened when the store is constructed, but the embedding model is
    deliberately loaded only when an operation needs an embedding.  This keeps
    importing the API (and health/library requests) fast and usable in a
    process that has not yet asked a question or indexed a file.
    """

    def __init__(
        self,
        persist_dir: Path,
        collection: str,
        embedding_model: str,
        embedding_provider: str | None = None,
        hf_api_token: str | None = None,
    ):
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - dependency environment
            raise RuntimeError(
                "Vector search requires the 'chromadb' package. Install dependencies with: "
                "pip install -r requirements.txt"
            ) from exc

        import os as _os

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection
        self.embedding_model_name = embedding_model
        self.embedding_provider = (
            embedding_provider or _os.getenv("EMBEDDING_PROVIDER", "local")
        ).lower()
        self.hf_api_token = (
            hf_api_token
            if hf_api_token is not None
            else _os.getenv("HF_API_TOKEN", "")
        )
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.col = self.client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )
        self.model: Any | None = None

    def _ensure_model(self) -> Any:
        if self.model is not None:
            return self.model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - dependency environment
            raise RuntimeError(
                "Embedding support requires the 'sentence-transformers' package. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc
        self.model = SentenceTransformer(self.embedding_model_name)
        return self.model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.embedding_provider == "hf":
            return self._embed_hf(texts)
        return self._ensure_model().encode(texts, normalize_embeddings=True).tolist()

    def _embed_hf(self, texts: list[str]) -> list[list[float]]:
        """Embed via the Hugging Face Inference API (no local torch needed)."""
        import time

        import requests

        if not self.hf_api_token:
            raise RuntimeError(
                "HF_API_TOKEN is not set. Get a free token at "
                "https://huggingface.co/settings/tokens and set HF_API_TOKEN, "
                "or use EMBEDDING_PROVIDER=local."
            )
        url = (
            "https://api-inference.huggingface.co/models/"
            f"{self.embedding_model_name}"
        )
        headers = {"Authorization": f"Bearer {self.hf_api_token}"}
        last_error = ""
        for attempt in range(4):
            try:
                resp = requests.post(
                    url, headers=headers, json={"inputs": texts}, timeout=120
                )
            except requests.exceptions.ConnectionError as exc:
                raise ConnectionError(
                    "Could not reach the Hugging Face Inference API."
                ) from exc
            except requests.exceptions.Timeout as exc:
                raise TimeoutError("The embedding API timed out. Please retry.") from exc
            if resp.status_code == 503:  # model cold-start: wait and retry
                try:
                    wait = float(resp.json().get("estimated_time", 20))
                except Exception:
                    wait = 20
                time.sleep(min(wait, 60))
                last_error = "model loading"
                continue
            if resp.status_code in (400, 401, 403, 404):
                raise RuntimeError(
                    f"Embedding API error (HTTP {resp.status_code}): {resp.text[:200]}"
                )
            resp.raise_for_status()
            data = resp.json()
            vectors = data if isinstance(data, list) else data.get("embeddings", data)
            return [[float(value) for value in row] for row in vectors]
        raise RuntimeError(
            f"Embedding model still loading after retries ({last_error}). Please retry."
        )

    @staticmethod
    def _id(chunk: dict[str, Any]) -> str:
        return hashlib.sha1(
            f"{chunk.get('source', '')}|{chunk.get('page')}|{chunk.get('chunk', 0)}|{chunk.get('text', '')}".encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _metadata(chunk: dict[str, Any]) -> dict[str, Any]:
        # Chroma metadata values cannot be None, so keep the historical 0
        # representation for an absent page.  Query converts it back to None.
        metadata: dict[str, Any] = {
            "source": str(chunk.get("source", "")),
            "page": chunk.get("page") or 0,
            "chunk": int(chunk.get("chunk", 0)),
        }
        if chunk.get("section"):
            metadata["section"] = str(chunk["section"])
        return metadata

    def delete_source(self, source: str) -> None:
        """Delete every indexed chunk belonging to one source filename."""
        if not source:
            return
        self.col.delete(where={"source": source})

    def add(self, chunks: list[dict], replace: bool = True) -> int:
        """Index chunks and optionally replace old chunks for their sources.

        Replacement is the default so re-indexing a changed file cannot leave
        stale chunks behind.  Embeddings are computed before deleting the old
        source, which preserves the previous index if model inference fails.
        """
        if not chunks:
            return 0

        texts = [str(c.get("text", "")) for c in chunks]
        ids = [self._id(c) for c in chunks]
        embeddings = self._embed(texts)
        source_names = {str(c.get("source", "")) for c in chunks if c.get("source")}
        if replace:
            for source in source_names:
                self.delete_source(source)

        self.col.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=[self._metadata(c) for c in chunks],
        )
        return len(chunks)

    def replace_source(self, source: str, chunks: list[dict]) -> int:
        """Replace one source, including the zero-chunk (empty document) case."""
        normalized = [dict(chunk, source=source) for chunk in chunks]
        if not normalized:
            self.delete_source(source)
            return 0
        return self.add(normalized, replace=True)

    def query(self, question: str, k: int = 4) -> list[dict]:
        count = self.col.count()
        if count == 0 or k <= 0:
            return []
        result = self.col.query(
            query_embeddings=self._embed([question]), n_results=min(k, count)
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits = []
        for index, (doc, metadata) in enumerate(zip(documents, metadatas)):
            meta = metadata or {}
            distance = distances[index] if index < len(distances) else None
            score = 1.0 - float(distance) if distance is not None else 0.0
            hits.append(
                {
                    "text": doc or "",
                    "source": meta.get("source", ""),
                    "page": meta.get("page") or None,
                    "section": meta.get("section"),
                    "chunk": meta.get("chunk", 0),
                    "score": score,
                }
            )
        return hits

    def sources(self) -> list[str]:
        if self.col.count() == 0:
            return []
        metadatas = self.col.get(include=["metadatas"]).get("metadatas") or []
        return sorted({str(meta.get("source")) for meta in metadatas if meta and meta.get("source")})

    def count(self) -> int:
        """Return the number of indexed chunks without loading embeddings."""
        return int(self.col.count())

    def reset(self) -> None:
        self.client.delete_collection(self.collection_name)
        self.col = self.client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"}
        )
