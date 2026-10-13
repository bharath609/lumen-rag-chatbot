# Local React API

Start the backend from `rag-chatbot/`:

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

The API is intentionally local-only. CORS accepts loopback origins such as
`http://localhost:5173`; `RAG_CORS_ORIGINS` may add more local origins, but
non-local values are ignored.

## Endpoints

- `GET /api/health` — service and indexed document/chunk counts.
- `GET /api/library` — `{documents, total, chunks}`. Each document includes
  `source`, `size`, `type`, `chunk_count`, `created_at`, and `updated_at`.
- `POST /api/documents` — multipart form with one or more `files` fields.
  Filenames are flattened/sanitized. Re-uploading a filename replaces its
  old chunks and registry record.
- `POST /api/chat` — JSON body such as:

  ```json
  {
    "question": "What does the report recommend?",
    "history": [
      {"role": "user", "content": "Summarize the report."},
      {"role": "assistant", "content": "..."}
    ]
  }
  ```

  The response contains `answer`, grounded `citations`/`sources`, and
  retrieval `metrics`.
- `DELETE /api/library` — clears the registry, uploaded files, and vector
  collection.

Supported uploads include PDF, DOCX, PPTX, XLS/XLSX/XLSM, CSV/TSV, HTML, JSON,
Markdown, and a broad set of plain-text/code formats. The format readers for PDF,
DOCX, PPTX, XLS/XLSX are loaded only when needed and report an install command if
their optional dependency is missing. Scanned/image-only PDFs still need OCR.
