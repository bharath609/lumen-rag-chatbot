"""Vector storage for Lumora.

When ``DATABASE_URL`` points at Supabase Postgres, chunks and embeddings are
stored in a ``pgvector`` table.  That makes the library durable on hosts with
an ephemeral filesystem (Render's free tier wipes local disk on every restart
or deploy).  Without ``DATABASE_URL`` the original ChromaDB store is used;
Chroma Cloud keeps working through its own environment variables.

Both backends expose the same small API used by the API, Streamlit app, and
CLI: ``add``, ``replace_source``, ``delete_source``, ``query``, ``sources``,
``library_records``, ``count`` and ``reset``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

TABLE = "public.document_chunks"
_POSTGRES_PREFIXES = ("postgres://", "postgresql://")


def _embedding_dimensions() -> int:
    """Dimension used by both Gemini embeddings and the pgvector column."""
    try:
        value = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    except (TypeError, ValueError):
        return 1536
    return value if value > 0 else 1536


def _vector_literal(values: list[float]) -> str:
    """Format an embedding as a pgvector text literal, e.g. ``[0.1,0.2]``."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


class VectorStore:
    """Persistent vector store backed by Supabase pgvector or ChromaDB.

    Connecting and creating the pgvector schema happens in the constructor;
    the embedding model itself stays lazy so health and library requests do
    not download or load a model.
    """

    def __init__(
        self,
        persist_dir: Path,
        collection: str,
        embedding_model: str,
        embedding_provider: str | None = None,
        hf_api_token: str | None = None,
    ):
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection
        self.embedding_model_name = embedding_model
        self.embedding_provider = (
            embedding_provider or os.getenv("EMBEDDING_PROVIDER", "local")
        ).lower()
        self.hf_api_token = (
            hf_api_token
            if hf_api_token is not None
            else os.getenv("HF_API_TOKEN", "")
        )
        self.dimensions = _embedding_dimensions()
        self.model: Any | None = None
        self.backend = "chroma"

        db_url = (os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or "").strip()
        if db_url.startswith(_POSTGRES_PREFIXES):
            self.backend = "supabase"
            self.db_url = db_url
            self.dimensions = _embedding_dimensions()
            self._ensure_schema()
            return

        self._init_chroma()

    # ------------------------------------------------------------------
    # ChromaDB fallback
    # ------------------------------------------------------------------
    def _init_chroma(self) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - dependency environment
            raise RuntimeError(
                "Vector search requires the 'chromadb' package. Install dependencies with: "
                "pip install -r requirements.txt"
            ) from exc

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        cloud_key = os.getenv("CHROMA_API_KEY", "")
        cloud_tenant = os.getenv("CHROMA_TENANT", "")
        cloud_database = os.getenv("CHROMA_DATABASE", "")
        if cloud_key and cloud_tenant and cloud_database and hasattr(
            chromadb, "CloudClient"
        ):
            self.client = chromadb.CloudClient(
                api_key=cloud_key,
                tenant=cloud_tenant,
                database=cloud_database,
            )
        else:
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.col = self.client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"}
        )

    # ------------------------------------------------------------------
    # Supabase / pgvector plumbing
    # ------------------------------------------------------------------
    def _connect(self, autocommit: bool = False):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - dependency environment
            raise RuntimeError(
                "Supabase vector storage requires the 'psycopg[binary]' package. "
                "Install dependencies with: pip install -r requirements.txt"
            ) from exc
        try:
            return psycopg.connect(
                self.db_url,
                connect_timeout=15,
                # Supabase's transaction pooler does not support prepared
                # statements that outlive a transaction.
                prepare_threshold=None,
                autocommit=autocommit,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not connect to Supabase Postgres. Check DATABASE_URL "
                f"(use the Transaction pooler connection string): {exc}"
            ) from exc

    def _ensure_schema(self) -> None:
        """Create the pgvector extension, table, indexes, and RLS guard.

        Every statement runs in autocommit mode so an unsupported optional
        index cannot roll back the table creation.  The table is owned by the
        Postgres role in DATABASE_URL; RLS plus revoked grants keep the public
        anon/authenticated roles from reading it through PostgREST.
        """
        dimensions = int(self.dimensions)
        try:
            with self._connect(autocommit=True) as conn:
                conn.execute("create extension if not exists vector")
                conn.execute(
                    f"""
                    create table if not exists {TABLE} (
                        id text primary key,
                        user_id text not null,
                        source text not null,
                        page integer,
                        chunk integer not null default 0,
                        section text,
                        doc_bytes bigint,
                        doc_type text,
                        text text not null,
                        embedding vector({dimensions}) not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
                conn.execute(
                    f"create index if not exists document_chunks_user_source_idx "
                    f"on {TABLE} (user_id, source)"
                )
                try:
                    conn.execute(
                        f"create index if not exists document_chunks_embedding_idx "
                        f"on {TABLE} using hnsw (embedding vector_cosine_ops)"
                    )
                except Exception:
                    # Older pgvector builds without HNSW still support exact
                    # search through the cosine operator.
                    pass
                conn.execute(f"alter table {TABLE} enable row level security")
                try:
                    conn.execute(
                        f"revoke all on {TABLE} from anon, authenticated"
                    )
                except Exception:
                    # Roles only exist on Supabase; ignore on plain Postgres.
                    pass
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "Could not prepare the Supabase vector table. Run "
                "'create extension if not exists vector;' in the Supabase SQL "
                f"editor, then retry: {exc}"
            ) from exc

    def _check_dimensions(self, embeddings: list[list[float]]) -> None:
        if self.backend != "supabase" or not embeddings:
            return
        expected = int(self.dimensions)
        actual = len(embeddings[0])
        if any(len(vector) != expected for vector in embeddings):
            raise RuntimeError(
                f"Embedding dimension {actual} does not match the pgvector "
                f"column vector({expected}). Set EMBEDDING_DIMENSIONS={actual} "
                "and recreate the table, or use a model that returns "
                f"{expected} dimensions."
            )

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
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
        import requests

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and set GEMINI_API_KEY."
            )
        model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
        vectors: list[list[float]] = []
        # pgvector needs a fixed width; Chroma keeps the model default so an
        # existing local collection does not change shape.
        dimensions = int(self.dimensions) if self.backend == "supabase" else None
        # The Gemini batch endpoint accepts at most 100 requests per call,
        # so large documents are embedded in chunks of 90 for headroom.
        for start in range(0, len(texts), 90):
            batch = texts[start : start + 90]
            requests_body = []
            for text in batch:
                item: dict[str, Any] = {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text}]},
                }
                if dimensions:
                    # Matryoshka embeddings let us ask for exactly the
                    # dimension stored in pgvector (default 1536).
                    item["outputDimensionality"] = dimensions
                requests_body.append(item)
            body = {"requests": requests_body}
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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def delete_source(self, source: str, user_id: str | None = None) -> None:
        """Delete every indexed chunk belonging to one source filename."""
        if not source:
            return
        if self.backend == "supabase":
            sql = f"delete from {TABLE} where source = %s"
            params: list[Any] = [source]
            if user_id:
                sql += " and user_id = %s"
                params.append(str(user_id))
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
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
        embeddings = self._embed(texts)

        if self.backend == "supabase":
            self._check_dimensions(embeddings)
            return self._add_supabase(chunks, texts, embeddings, replace, user_id)

        ids = [self._id(c) for c in chunks]
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

    def _add_supabase(
        self,
        chunks: list[dict],
        texts: list[str],
        embeddings: list[list[float]],
        replace: bool,
        user_id: str | None,
    ) -> int:
        effective_user_id = user_id or next(
            (str(c.get("user_id")) for c in chunks if c.get("user_id")), ""
        )
        rows: list[tuple[Any, ...]] = []
        source_names: set[str] = set()
        for chunk, text, embedding in zip(chunks, texts, embeddings):
            uid = str(chunk.get("user_id") or effective_user_id or "")
            prepared = {**chunk, "user_id": uid}
            source = str(prepared.get("source", ""))
            if source:
                source_names.add(source)
            page = prepared.get("page")
            rows.append(
                (
                    self._id(prepared),
                    uid,
                    source,
                    int(page) if page else None,
                    int(prepared.get("chunk", 0) or 0),
                    str(prepared["section"]) if prepared.get("section") else None,
                    int(prepared["doc_bytes"]) if prepared.get("doc_bytes") else None,
                    str(prepared["doc_type"]) if prepared.get("doc_type") else None,
                    text,
                    _vector_literal(embedding),
                )
            )

        with self._connect() as conn, conn.cursor() as cur:
            if replace:
                for source in sorted(source_names):
                    cur.execute(
                        f"delete from {TABLE} where source = %s and user_id = %s",
                        (source, str(effective_user_id)),
                    )
            cur.executemany(
                f"""
                insert into {TABLE}
                    (id, user_id, source, page, chunk, section, doc_bytes,
                     doc_type, text, embedding)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                on conflict (id) do update set
                    user_id = excluded.user_id,
                    source = excluded.source,
                    page = excluded.page,
                    chunk = excluded.chunk,
                    section = excluded.section,
                    doc_bytes = excluded.doc_bytes,
                    doc_type = excluded.doc_type,
                    text = excluded.text,
                    embedding = excluded.embedding
                """,
                rows,
            )
        return len(rows)

    def replace_source(
        self, source: str, chunks: list[dict], user_id: str | None = None
    ) -> int:
        """Replace one source, including the zero-chunk (empty document) case."""
        normalized = [dict(chunk, source=source, user_id=user_id or chunk.get("user_id")) for chunk in chunks]
        if not normalized:
            self.delete_source(source, user_id)
            return 0
        return self.add(normalized, replace=True, user_id=user_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def query(
        self,
        question: str,
        k: int = 4,
        sources: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        if k <= 0:
            return []
        if self.backend == "supabase":
            return self._query_supabase(question, k, sources, user_id)

        count = self.col.count()
        if count == 0:
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

    def _query_supabase(
        self,
        question: str,
        k: int,
        sources: list[str] | None,
        user_id: str | None,
    ) -> list[dict]:
        embedding = _vector_literal(self._embed([question])[0])
        clauses: list[str] = []
        params: list[Any] = [embedding]
        if user_id:
            clauses.append("user_id = %s")
            params.append(str(user_id))
        if sources:
            clauses.append("source = any(%s::text[])")
            params.append(sorted({str(source) for source in sources}))
        where = (" where " + " and ".join(clauses)) if clauses else ""
        sql = (
            f"select text, source, page, chunk, section, "
            f"1 - (embedding <=> %s::vector) as score from {TABLE}{where} "
            f"order by embedding <=> %s::vector limit %s"
        )
        params.extend([embedding, int(k)])
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [
            {
                "text": row[0] or "",
                "source": row[1] or "",
                "page": row[2] or None,
                "chunk": int(row[3] or 0),
                "section": row[4],
                "score": float(row[5]),
            }
            for row in rows
        ]

    def sources(self) -> list[str]:
        if self.backend == "supabase":
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"select distinct source from {TABLE} order by source")
                return [row[0] for row in cur.fetchall() if row[0]]
        if self.col.count() == 0:
            return []
        metadatas = self.col.get(include=["metadatas"]).get("metadatas") or []
        return sorted({str(meta.get("source")) for meta in metadatas if meta and meta.get("source")})

    def library_records(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Describe every indexed source using only what the index stores."""
        if self.backend == "supabase":
            sql = (
                f"select source, count(*)::int as chunk_count, "
                f"coalesce(max(page), 0)::int as page_count, "
                f"coalesce(max(doc_bytes), 0)::bigint as doc_bytes, "
                f"coalesce(max(doc_type), '') as doc_type "
                f"from {TABLE}"
            )
            params: list[Any] = []
            if user_id:
                sql += " where user_id = %s"
                params.append(str(user_id))
            sql += " group by source order by source"
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
            return [
                {
                    "source": row[0],
                    "chunk_count": int(row[1] or 0),
                    "page_count": int(row[2] or 0),
                    "doc_bytes": int(row[3] or 0),
                    "doc_type": row[4] or "",
                }
                for row in rows
            ]

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
        if self.backend == "supabase":
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"select count(*)::bigint from {TABLE}")
                row = cur.fetchone()
            return int(row[0] if row else 0)
        return int(self.col.count())

    def reset(self, user_id: str | None = None) -> None:
        if self.backend == "supabase":
            if user_id:
                with self._connect() as conn, conn.cursor() as cur:
                    cur.execute(
                        f"delete from {TABLE} where user_id = %s", (str(user_id),)
                    )
            else:
                with self._connect() as conn, conn.cursor() as cur:
                    cur.execute(f"delete from {TABLE}")
            return

        if user_id:
            self.col.delete(where={"user_id": user_id})
            return
        self.client.delete_collection(self.collection_name)
        self.col = self.client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"}
        )
