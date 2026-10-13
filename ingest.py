"""CLI: index files or folders.  Usage: python ingest.py path/to/file_or_folder [...]"""
import argparse
from pathlib import Path

from src.chunking import chunk_pages
from src.config import settings
from src.loaders import SUPPORTED, load_file
from src.vectorstore import VectorStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    store = VectorStore(settings.persist_dir, settings.collection, settings.embedding_model)
    files = []
    for p in map(Path, args.paths):
        files += [f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED] if p.is_dir() else [p]

    for f in files:
        chunks = chunk_pages(load_file(f), settings.chunk_size, settings.chunk_overlap)
        print(f"{f.name}: indexed {store.add(chunks)} chunks")


if __name__ == "__main__":
    main()
