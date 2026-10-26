import json
from unittest.mock import Mock, patch

import pytest

from api import LibraryRegistry, local_origin, sanitize_filename
from src.auth import require_user


def test_sanitize_filename_flattens_paths_and_unsafe_characters():
    assert sanitize_filename(r"..\reports/quarter 1?.pdf") == "quarter_1_.pdf"
    assert sanitize_filename(".env") == "env"
    assert sanitize_filename(None) == "upload"


def test_cors_origin_accepts_loopback_only():
    assert local_origin("http://localhost:5173")
    assert local_origin("https://127.0.0.1:8000")
    assert not local_origin("https://example.com")


def test_library_registry_upserts_and_preserves_created_timestamp(tmp_path):
    registry = LibraryRegistry(tmp_path / "library.json")
    first = registry.upsert(
        {
            "source": "report.txt",
            "size": 5,
            "type": "text/plain",
            "chunk_count": 1,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
    )
    registry.upsert(
        {
            "source": "report.txt",
            "size": 10,
            "type": "text/plain",
            "chunk_count": 2,
            "created_at": "2025-01-02T00:00:00+00:00",
            "updated_at": "2025-01-02T00:00:00+00:00",
        }
    )

    assert first["created_at"] == "2025-01-01T00:00:00+00:00"
    assert registry.read() == [
        {
            "source": "report.txt",
            "size": 10,
            "type": "text/plain",
            "chunk_count": 2,
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-02T00:00:00+00:00",
        }
    ]
    assert json.loads((tmp_path / "library.json").read_text())


def test_supabase_auth_returns_user_id(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-key")
    response = Mock(status_code=200)
    response.json.return_value = {"id": "user-123", "email": "person@example.com"}
    with patch("src.auth.requests.get", return_value=response) as get:
        user = require_user("Bearer access-token")
    assert user["id"] == "user-123"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer access-token"


def test_supabase_auth_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-key")
    with pytest.raises(Exception) as error:
        require_user(None)
    assert getattr(error.value, "status_code", None) == 401
