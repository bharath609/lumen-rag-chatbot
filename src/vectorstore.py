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
        cloud_key = _os.getenv("CHROMA_API_KEY", "")
        cloud_tenant = _os.getenv("CHROMA_TENANT", "")
        cloud_database = _os.getenv("CHROMA_DATABASE", "")
        if cloud_key and cloud_tenant and cloud_database and hasattr(
            chromadb, "CloudClient"
        ):
            # Persistent Chroma Cloud database: the index survives restarts of
            # ephemeral hosts (Render free tier) that would wipe local storage.
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.CloudClient(
                api_key=cloud_key,
                tenant=cloud_tenant,
                database=cloud_database,
            )
        else:
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
        if self.embedding_provider == "gemini":
            return self._embed_gemini(texts)
        return self._ensure_model().encode(texts, normalize_embeddings=True).tolist()

    def _embed_gemini(self, texts: list[str]) -> list[list[float]]:
        """Embed via the Google Gemini embedding API (no local torch needed)."""
        import os as _os

        import requests

        api_key = _os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and set GEMINI_API_KEY."
            )
        model = _os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
        vectors: list[list[float]] = []
        # The Gemini batch endpoint accepts at most 100 requests per call,
        # so large documents are embedded in chunks of 90 for headroom.
        for start in range(0, len(texts), 90):
            batch = texts[start : start + 90]
            body = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": text}]},
                    }
                    for text in batch
                ]
            }
            try:
                resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
            except requests.exceptions.ConnectionError as exc:
                raise ConnectionError(
                    "Could not reach the Gemini API. Check network and retry."
                ) from exc
            except requests.exceptions.Timeout as exc:
                raise TimeoutError("The embedding API timed out. Please retry.") from exc
            if resp.status_code in (400, 401, 403, 404, 429):
                detail = resp.text[:300]
                try:
                    detail = resp.json().get("error", {}).get("message", detail)
                except Exception:
                    pass
                raise RuntimeError(
                    f"Embedding API error (HTTP {resp.status_code}): {detail}"
                )
            resp.raise_for_status()
            try:
                embeddings = resp.json()["embeddings"]
                vectors.extend(
                    [float(value) for value in item["values"]] for item in embeddings
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Gemini returned an unexpected embedding shape."
                ) from exc
        return vectors

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
            "https://router.huggingface.co/hf-inference/models/"
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
            f"{chunk.get('user_id', '')}|{chunk.get('source', '')}|{chunk.get('page')}|{chunk.get('chunk', 0)}|{chunk.get('text', '')}".encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _metadata(chunk: dict[str, Any]) -> dict[str, Any]:
        # Chroma metadata values cannot be None, so keep the historical 0
        # representation for an absent page.  Query converts it back to None.
        metadata: dict[str, Any] = {
            "user_id": str(chunk.get("user_id", "")),
            "source": str(chunk.get("source", "")),
            "page": chunk.get("page") or 0,
            "chunk": int(chunk.get("chunk", 0)),
        }
        if chunk.get("section"):
            metadata["section"] = str(chunk["section"])
        # File metadata rides on every chunk so the library registry can be
        # rebuilt from the index itself (used when a host's disk is wiped).
        if chunk.get("doc_bytes"):
            metadata["doc_bytes"] = int(chunk["doc_bytes"])
        if chunk.get("doc_type"):
            metadata["doc_type"] = str(chunk["doc_type"])
        return metadata

    def delete_source(self, source: str, user_id: str | None = None) -> None:
        """Delete every indexed chunk belonging to one source filename."""
        if not source:
            return
        where: dict[str, Any] = {"source": source}
        if user_id:
            where = {"$and": [{"user_id": user_id}, where]}
        self.col.delete(where=where)

    def add(self, chunks: list[dict], replace: bool = True, user_id: str | None = None) -> int:
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
        effective_user_id = user_id or next(
            (str(c.get("user_id")) for c in chunks if c.get("user_id")), None
        )
        if replace:
            for source in source_names:
                self.delete_source(source, effective_user_id)

        self.col.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=[self._metadata(c) for c in chunks],
        )
        return len(chunks)

    def replace_source(
        self, source: str, chunks: list[dict], user_id: str | None = None
    ) -> int:
        """Replace one source, including the zero-chunk (empty document) case."""
        normalized = [dict(chunk, source=source, user_id=user_id or chunk.get("user_id")) for chunk in chunks]
        if not normalized:
            self.delete_source(source, user_id)
            return 0
        return self.add(normalized, replace=True, user_id=user_id)

    def query(
        self,
        question: str,
        k: int = 4,
        sources: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        count = self.col.count()
        if count == 0 or k <= 0:
            return []
        where: dict[str, Any] | None = None
        filters: list[dict[str, Any]] = []
        if user_id:
            filters.append({"user_id": user_id})
        if sources:  # restrict retrieval to specific documents
            filters.append({"source": {"$in": sorted(set(sources))}})
        if len(filters) == 1:
            where = filters[0]
        elif filters:
            where = {"$and": filters}
        result = self.col.query(
            query_embeddings=self._embed([question]),
            n_results=min(k, count),
            where=where,
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

    def library_records(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Describe every indexed source using only what the index stores.

        Used to rebuild the library registry after an ephemeral host wipes the
        local filesystem: the cloud index is the durable source of truth.
        """
        if self.col.count() == 0:
            return []
        where = {"user_id": user_id} if user_id else None
        result = self.col.get(include=["metadatas"], where=where)
        metadatas = result.get("metadatas") or []
        grouped: dict[str, dict[str, Any]] = {}
        for meta in metadatas:
            if not isinstance(meta, dict) or not meta.get("source"):
                continue
            source = str(meta["source"])
            record = grouped.setdefault(
                source,
                {
                    "source": source,
                    "chunk_count": 0,
                    "page_count": 0,
                    "doc_bytes": 0,
                    "doc_type": "",
                },
            )
            record["chunk_count"] += 1
            page = int(meta.get("page") or 0)
            record["page_count"] = max(record["page_count"], page)
            record["doc_bytes"] = record["doc_bytes"] or int(meta.get("doc_bytes") or 0)
            record["doc_type"] = record["doc_type"] or str(meta.get("doc_type") or "")
        return [grouped[source] for source in sorted(grouped)]

    def count(self) -> int:
        """Return the number of indexed chunks without loading embeddings."""
        return int(self.col.count())

    def reset(self, user_id: str | None = None) -> None:
        if user_id:
            self.col.delete(where={"user_id": user_id})
            return
        self.client.delete_collection(self.collection_name)
        self.col = self.client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"}
        )
