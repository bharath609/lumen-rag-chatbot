# Lumen — grounded document intelligence

Lumen is a local-first Retrieval-Augmented Generation (RAG) chatbot. Upload common
documents, ask questions in a conversational workspace, and inspect the passages that
ground each answer. React is the UI layer; the product is the RAG system: ingestion,
structure-aware chunking, local embeddings, vector retrieval, a relevance gate, and
citation-aware generation.

It runs locally by default with Ollama, so documents and embeddings can stay on your
machine. Anthropic is available as an optional hosted generation provider.

## How it works

```text
Upload -> parse -> structure-aware chunks -> embeddings -> persistent ChromaDB index
                                                          |
Question -> query embedding -> top-k retrieval -> relevance gate -> grounded prompt
                                                          |
                                      answer + citations + retrieval metrics
```

Why each piece:

- **Overlap-aware chunking** keeps ideas intact across chunk boundaries.
- **Local embeddings** mean documents do not leave the machine when using Ollama.
- **A similarity threshold** skips generation when nothing relevant was retrieved,
  reducing unsupported answers.
- **Transparent evidence** exposes the retrieved excerpts, source location, score,
  and context metrics behind each response.
- **A pluggable LLM** supports local Ollama by default and optional Anthropic API use.
- **A safe local API** binds to loopback by default and only accepts loopback browser
  origins through CORS.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Mac/Linux: cp .env.example .env

# Local LLM (free): install Ollama from ollama.com, then:
ollama pull llama3.2:3b

# Terminal 1: start the RAG API from this folder
uvicorn api:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: start the Lumen UI
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>, upload documents in the library sidebar, and ask
questions. If the API is not running, the UI clearly switches to a local demo mode
so the interface can still be explored; demo answers are labeled and are not live RAG.

The original Streamlit client remains available for a lightweight Python-only flow:

```bash
streamlit run app.py
```

Index from the command line instead: `python ingest.py data/sample`.

### Use the Anthropic API instead of Ollama

In `.env`: `LLM_PROVIDER=anthropic`, `LLM_MODEL=<model name from Anthropic docs>`,
and `ANTHROPIC_API_KEY=...`.

## Supported documents

The API extracts text from PDF, DOCX, PPTX, XLS/XLSX/XLSM, CSV/TSV, HTML, JSON,
Markdown, and a broad set of plain-text/code formats such as TXT, XML, YAML, SQL,
Python, JavaScript, TypeScript, Java, C/C++, Go, Rust, shell, and CSS. Format
readers are loaded only when needed. Scanned or image-only PDFs need an OCR layer
before they contain searchable text; binary formats not listed above are rejected
with a clear message.

## Project structure

```text
api.py              FastAPI boundary for the Lumen UI
app.py              Streamlit fallback UI + upload sidebar
ingest.py           CLI indexer
frontend/           React/Vite Lumen workspace
src/config.py       Settings from .env
src/loaders.py      Multi-format extraction into text pages
src/chunking.py     Overlap-aware natural-boundary chunker
src/vectorstore.py ChromaDB + lazy sentence-transformer embeddings
src/llm.py          Ollama / Anthropic wrapper
src/rag.py          Retrieval, relevance gate, context, citations, metrics
tests/              pytest coverage for chunking, loaders, API, and RAG
```

## Checks

Backend tests:

```bash
python -m pytest -q
```

Frontend production check (from `frontend/`):

```bash
npm run build
```

## Honest limitations / next experiments

- Scanned PDFs (images) have no extractable text yet; add optional OCR for them.
- Retrieval currently uses semantic similarity and a relevance threshold; a hybrid
  BM25 + vector retriever or reranker would be a sensible next experiment.
- The local API is designed for one trusted machine, not multi-tenant deployment.
- Grounding is enforced by context selection and a no-hit short circuit. A production
  deployment could also validate citation markers against generated text.

## Resume bullets (edit to match what you actually built)

- Built a local-first Retrieval-Augmented Generation chatbot with a React/Vite
  evidence workspace and a FastAPI boundary for multi-format document ingestion.
- Implemented overlap-aware natural-boundary chunking, lazy local sentence-transformer
  embeddings, and a persistent ChromaDB cosine index with source replacement semantics.
- Added a relevance gate that skips generation for out-of-scope questions, plus
  grounded citations and retrieval metrics for every answer.
- Designed a pluggable Ollama/Anthropic LLM layer, safe loopback API, demo fallback,
  and pytest coverage for the core retrieval and ingestion boundaries.
