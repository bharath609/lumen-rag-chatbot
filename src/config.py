"""Central settings, read from environment variables / .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "llama3.2:3b")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "local")  # local | hf | gemini
    hf_api_token: str = os.getenv("HF_API_TOKEN", "")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "150"))
    top_k: int = int(os.getenv("TOP_K", "4"))
    min_score: float = float(os.getenv("MIN_SCORE", "0.25"))
    persist_dir: Path = ROOT / "chroma_db"
    upload_dir: Path = ROOT / "data" / "uploads"
    collection: str = "documents"


settings = Settings()
