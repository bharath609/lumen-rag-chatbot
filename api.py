"""FastAPI backend for the local React RAG client.

Run with ``uvicorn api:app --reload`` from this directory.  Importing this
module does not construct a VectorStore or load the embedding model; that work
starts when an upload or chat request needs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.chunking import chunk_pages
from src.config import settings
from src.loaders import LoaderDependencyError, SUPPORTED, load_file
from src.rag import answer
from src.vectorstore import VectorStore


_store: VectorStore | None = None
_store_key: tuple[str, str, str] | None = None
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CLOCK$",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "CON",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
    "NUL",
    "PRN",
}


def sanitize_filename(filename: str | None) -> str:
    """Return a flat, filesystem-safe filename while retaining its extension."""
    raw = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    raw = _CONTROL_CHARS.sub("", raw).strip()
    raw = _SAFE_FILENAME.sub("_", raw)
    raw = raw.strip(" .")
    # A leading dot can otherwise create a hidden control file such as .env.
    raw = raw.lstrip(".")
    if len(raw) > 180:
        suffix = Path(raw).suffix
        if len(suffix) >= 180:
            raw = raw[:180]
        else:
            stem = raw[: -len(suffix)] if suffix else raw
            raw = stem[: 180 - len(suffix)] + suffix
    if Path(raw).stem.upper() in _WINDOWS_RESERVED_NAMES:
        raw = f"_{raw}"
    return raw or "upload"


def is_supported_filename(filename: str | None) -> bool:
    return Path(sanitize_filename(filename)).suffix.lower() in SUPPORTED


def local_origin(origin: str | None) -> bool:
    """Whether an Origin is a local HTTP(S) origin suitable for this API."""
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in _LOCAL_HOSTS


def _configured_local_origins() -> list[str]:
    configured = os.getenv("RAG_CORS_ORIGINS", "")
    origins = [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    return [origin for origin in origins if local_origin(origin)]


def _configured_public_origins() -> list[str]:
    """Extra browser origins allowed via RAG_CORS_ORIGINS (e.g. hosted frontend).

    Only http(s) origins with a real hostname are accepted. Local development
    keeps working through the loopback regex below; production sets this to the
    public site URL, e.g. RAG_CORS_ORIGINS=https://<user>.github.io
    """
    configured = os.getenv("RAG_CORS_ORIGINS", "")
    origins: list[str] = []
    for item in configured.split(","):
        item = item.strip().rstrip("/")
        if not item:
            continue
        try:
            parsed = urlsplit(item)
        except ValueError:
            continue
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            origins.append(item)
    return origins


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _library_path() -> Path:
    return Path(settings.upload_dir).parent / "library.json"


class LibraryRegistry:
    """Small JSON registry that describes indexed source files."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else _library_path()

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # A damaged registry should not prevent the API from serving or
            # rebuilding the library; the vector index remains authoritative.
            return []
        if isinstance(value, dict):
            value = value.get("documents", [])
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        records = self.read()
        source = record["source"]
        existing = next((item for item in records if item.get("source") == source), None)
        if existing:
            record = {**existing, **record, "created_at": existing.get("created_at", record["created_at"])}
            records = [item for item in records if item.get("source") != source]
        records.append(record)
        records.sort(key=lambda item: str(item.get("source", "")).lower())
        self._write(records)
        return record

    def clear(self) -> list[dict[str, Any]]:
        records = self.read()
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                self._write([])
        return records


def _get_store() -> VectorStore:
    global _store, _store_key
    key = (str(settings.persist_dir), settings.collection, settings.embedding_model)
    if _store is None or _store_key != key:
        _store = VectorStore(
            settings.persist_dir,
            settings.collection,
            settings.embedding_model,
            settings.embedding_provider,
            settings.hf_api_token,
        )
        _store_key = key
    return _store


def _reset_store_for_tests() -> None:
    """Reset the module cache for lightweight API tests."""
    global _store, _store_key
    _store = None
    _store_key = None


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return dict(record)


def _record_chunk_count(record: dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("chunk_count", record.get("chunks", 0)) or 0))
    except (TypeError, ValueError):
        return 0


def _public_hit(hit: dict[str, Any]) -> dict[str, Any]:
    result = dict(hit)
    if result.get("score") is not None:
        result["score"] = float(result["score"])
    return result


def _clean_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content})
    return cleaned[-12:]


def _mime_type(filename: str, supplied: str | None) -> str:
    if supplied and supplied != "application/octet-stream":
        return supplied
    return mimetypes.guess_type(filename)[0] or supplied or "application/octet-stream"


async def _index_upload(upload: UploadFile, registry: LibraryRegistry) -> dict[str, Any]:
    source = sanitize_filename(upload.filename)
    extension = Path(source).suffix.lower()
    if extension not in SUPPORTED:
        supported = ", ".join(sorted(SUPPORTED))
        raise ValueError(f"Unsupported file type '{extension or '(none)'}'. Supported types: {supported}")

    payload = await upload.read()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_path = upload_dir / source

    # Parse and embed a temporary file first.  If a format dependency or the
    # embedding model fails, a previously indexed version remains untouched.
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{source}.", suffix=extension, dir=str(upload_dir)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        pages = load_file(temporary_name, source=source)
        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        # File metadata rides on every chunk so the library list can be
        # rebuilt straight from the persistent index after a host restart.
        doc_type = _mime_type(source, getattr(upload, "content_type", None))
        for chunk in chunks:
            chunk["doc_bytes"] = len(payload)
            chunk["doc_type"] = doc_type
        store = _get_store()
        replace_source = getattr(store, "replace_source", None)
        if callable(replace_source):
            replace_source(source, chunks)
        else:  # Keeps the API easy to exercise with a tiny fake store in tests.
            delete_source = getattr(store, "delete_source", None)
            if callable(delete_source):
                delete_source(source)
            store.add(chunks)
        os.replace(temporary_name, final_path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass

    now = _utc_now()
    previous = next((item for item in registry.read() if item.get("source") == source), None)
    record = {
        "source": source,
        "name": source,
        "size": len(payload),
        "type": _mime_type(source, getattr(upload, "content_type", None)),
        "extension": extension,
        "chunk_count": len(chunks),
        "chunks": len(chunks),
        "created_at": (previous or {}).get("created_at", now),
        "updated_at": now,
        "uploaded_at": now,
    }
    return registry.upsert(record)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    history: list[dict[str, Any]] | None = None
    sources: list[str] | None = None


def _rebuild_registry_from_index(registry: LibraryRegistry) -> None:
    """Repopulate library.json from the persistent index after a host wipe.

    Ephemeral hosts (Render free tier) lose uploaded files and the registry on
    every restart, but a cloud-backed vector index survives.  This restores
    the document list with the metadata each chunk carried (size, type).
    """
    store = _get_store()
    if store.count() == 0:
        return
    has_doc_meta = any(
        record.get("doc_bytes") for record in store.library_records()
    )
    if not has_doc_meta:
        # Index predates per-chunk file metadata; a rebuild would lose data.
        return
    now = _utc_now()
    for record in store.library_records():
        source = record["source"]
        extension = Path(source).suffix.lower()
        registry.upsert(
            {
                "source": source,
                "name": source,
                "size": record.get("doc_bytes") or 0,
                "type": record.get("doc_type") or extension,
                "extension": extension,
                "chunk_count": record.get("chunk_count", 0),
                "chunks": record.get("chunk_count", 0),
                "page_count": record.get("page_count"),
                "created_at": now,
                "updated_at": now,
                "uploaded_at": now,
            }
        )


def _seed_library_sync() -> None:
    """Index SEED_DIR documents once when the library is empty (hosted demos).

    Runs in a background thread after startup so slow first-time embedding
    downloads never block the app from serving /api/health. Set SEED_DIR=""
    to disable.
    """
    import asyncio as _asyncio

    seed_dir = os.getenv("SEED_DIR", "data/sample")
    registry = LibraryRegistry()
    if not registry.read():
        # A cloud-backed index outlives the host filesystem: recover the
        # previously uploaded documents instead of treating them as lost.
        try:
            _rebuild_registry_from_index(registry)
        except Exception as exc:
            log = logging.getLogger("lumen.seed")
            log.warning("Registry rebuild skipped: %s", exc)
    if not seed_dir:
        return
    path = Path(seed_dir)
    if not path.is_dir():
        return
    files = [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and item.suffix.lower() in SUPPORTED
    ]
    log = logging.getLogger("lumen.seed")
    for item in files:
        try:
            with item.open("rb") as handle:
                upload = UploadFile(file=handle, filename=item.name)
                _asyncio.run(_index_upload(upload, registry))
        except Exception as exc:  # best effort: one bad seed file skips, rest index
            log.warning("Skipping seed file %s: %s", item, exc)


async def _seed_library_async() -> None:
    await asyncio.to_thread(_seed_library_sync)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.get_running_loop().call_soon(
        lambda: asyncio.ensure_future(_seed_library_async())
    )
    yield


app = FastAPI(
    title="RAG Document Chatbot API", version="1.0.0", lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*_configured_local_origins(), *_configured_public_origins()],
    # Any localhost/loopback port is useful for Vite, CRA, and preview builds,
    # while the regex prevents accidental exposure to an external origin.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    records = LibraryRegistry().read()
    return {
        "status": "ok",
        "service": "rag-chatbot",
        "documents": len(records),
        "chunks": sum(_record_chunk_count(item) for item in records),
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
    }


@app.get("/api/library")
def library() -> dict[str, Any]:
    records = [_public_record(item) for item in LibraryRegistry().read()]
    return {
        "documents": records,
        "total": len(records),
        "chunks": sum(_record_chunk_count(item) for item in records),
    }


@app.post("/api/documents")
async def upload_documents(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one document is required")

    registry = LibraryRegistry()
    indexed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for upload in files:
        try:
            indexed.append(await _index_upload(upload, registry))
        except (
            LoaderDependencyError,
            ConnectionError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            errors.append(
                {
                    "source": sanitize_filename(upload.filename),
                    "error": str(exc),
                }
            )

    if not indexed and errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "No documents were indexed", "errors": errors},
        )
    return {
        "documents": [_public_record(item) for item in indexed],
        "indexed": len(indexed),
        "errors": errors,
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be blank")
    try:
        result = answer(
            question,
            _get_store(),
            settings,
            _clean_history(request.history or []),
            sources=request.sources,
        )
    except (ConnectionError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM offline: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "11434" in message or "ollama" in lowered or "connection" in lowered:
            raise HTTPException(
                status_code=502,
                detail=(
                    "LLM offline: Ollama is not reachable at "
                    f"{settings.ollama_host}. Start it with `ollama serve`, run "
                    f"`ollama pull {settings.llm_model}`, then retry."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail="Could not generate an answer. Please retry.") from exc
    return {
        "answer": result["answer"],
        "citations": [_public_hit(item) for item in result.get("citations", [])],
        "sources": [_public_hit(item) for item in result.get("sources", [])],
        "metrics": result.get("metrics", {}),
    }


@app.delete("/api/library")
def clear_library() -> dict[str, Any]:
    registry = LibraryRegistry()
    records = registry.clear()

    # Constructing VectorStore does not load the embedding model, so stale
    # Chroma chunks are removed even when this process has not handled a chat.
    if _store is not None:
        reset = getattr(_store, "reset", None)
        if callable(reset):
            reset()
    elif Path(settings.persist_dir).exists():
        _get_store().reset()

    upload_dir = Path(settings.upload_dir)
    if upload_dir.exists():
        for path in upload_dir.iterdir():
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
    return {"status": "ok", "deleted": len(records)}


if __name__ == "__main__":  # pragma: no cover - convenience for local use
    import uvicorn

    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
