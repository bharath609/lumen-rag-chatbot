"""Split long text into overlapping chunks, preferring natural boundaries."""


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text = text.strip()
    chunks: list[str] = []
    start, n = 0, len(text)

    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = text[start:end]
            # Prefer paragraph, then sentence, then line, then word boundary
            for sep in ("\n\n", ". ", "\n", " "):
                idx = window.rfind(sep)
                if idx > chunk_size * 0.5:
                    end = start + idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)  # always move forward
    return chunks


def chunk_pages(pages: list[dict], chunk_size: int, overlap: int) -> list[dict]:
    """Chunk each page; keep source/page metadata on every chunk."""
    out = []
    for p in pages:
        for i, c in enumerate(chunk_text(p["text"], chunk_size, overlap)):
            out.append({"text": c, "source": p["source"], "page": p["page"], "chunk": i})
    return out
