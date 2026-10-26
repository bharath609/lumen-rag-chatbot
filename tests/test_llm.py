from unittest.mock import Mock, patch

import pytest

from src.config import Settings
from src.llm import _generate_gemini


def _settings(model="gemini-2.5-flash"):
    return Settings(llm_provider="gemini", llm_model=model)


def _response(status_code, payload=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload or {}
    response.raise_for_status.side_effect = None
    return response


def test_gemini_retries_503_then_returns_answer(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")
    responses = [
        _response(503, {"error": {"message": "temporarily unavailable"}}),
        _response(200, {"candidates": [{"content": {"parts": [{"text": "Answer"}]}}]}),
    ]

    with patch("src.llm.requests.post", side_effect=responses) as post, patch("src.llm.time.sleep") as sleep:
        assert _generate_gemini("system", [{"role": "user", "content": "question"}], _settings()) == "Answer"

    assert post.call_count == 2
    sleep.assert_called_once()


def test_gemini_uses_fallback_model_after_transient_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    responses = [
        _response(503, {"error": {"message": "overloaded"}}),
        _response(200, {"candidates": [{"content": {"parts": [{"text": "Fallback answer"}]}}]}),
    ]

    with patch("src.llm.requests.post", side_effect=responses) as post:
        assert _generate_gemini("system", [{"role": "user", "content": "question"}], _settings()) == "Fallback answer"

    assert post.call_args_list[0].kwargs["params"] == {"key": "test-key"}
    assert "gemini-2.5-flash-lite:generateContent" in post.call_args_list[1].args[0]


def test_gemini_reports_transient_failure_after_retries(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    responses = [_response(503, {"error": {"message": "overloaded"}})] * 2

    with patch("src.llm.requests.post", side_effect=responses), patch("src.llm.time.sleep"):
        with pytest.raises(RuntimeError, match="temporarily unavailable.*503.*2 attempts"):
            _generate_gemini("system", [{"role": "user", "content": "question"}], _settings())
