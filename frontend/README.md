# Lumora frontend

Lumora is the React client for the local RAG document chatbot. It runs as a Vite
development server and uses relative `/api/*` requests, so it can talk to the
FastAPI service without exposing the backend to the public internet.

## Run locally

From `rag-chatbot/frontend`:

```bash
npm install
npm run dev
```

Then open <http://127.0.0.1:5173>. In a second terminal, start the backend
from `rag-chatbot`:

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

Vite proxies `/api` to `http://127.0.0.1:8000` using `frontend/vite.config.js`.
If the backend is not running, the client automatically switches to a local
demo workspace with sample documents, grounded sample answers, citations, and
simulated uploads so the interface can still be reviewed.

## Build / preview

```bash
npm run build
npm run preview
```

For a backend on another local origin, set `VITE_API_BASE_URL` before the Vite
command (for example, `VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev`).
The backend must allow the frontend origin through its local CORS settings.

The client calls:

- `GET /api/health` and `GET /api/library` on startup and refresh
- `POST /api/documents` for multipart uploads
- `POST /api/chat` for grounded responses and retrieval metrics
- `DELETE /api/library` when clearing the library
