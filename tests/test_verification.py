from src import verification
from src.config import Settings
from src.verification import _first_json, suggest_followups, verify_answer

S = Settings()


def good_generate(system, messages, s):
    assert "fact-check" in system.lower() or "follow-up" in system.lower()
    return '{"supported": true, "unsupported": []}'


def flagged_generate(system, messages, s):
    return 'Sure! {"supported": false, "unsupported": ["net worth of $4B", "founded 1987"]}'


def broken_generate(system, messages, s):
    raise RuntimeError("LLM offline")


def test_verify_supported():
    hits = [{"text": "a", "source": "s", "score": 0.9}]
    assert verify_answer("Paris is in a.txt", hits, S, good_generate) == {
        "status": "supported",
        "unsupported": [],
    }


def test_verify_flagged_extracts_claims():
    hits = [{"text": "a", "source": "s", "score": 0.9}]
    result = verify_answer("claims", hits, S, flagged_generate)
    assert result["status"] == "flagged"
    assert result["unsupported"] == ["net worth of $4B", "founded 1987"]


def test_verify_fail_open():
    hits = [{"text": "a", "source": "s", "score": 0.9}]
    assert verify_answer("x", hits, S, broken_generate) == {
        "status": "skipped",
        "unsupported": [],
    }


def test_verify_empty_answer_skipped():
    assert verify_answer("", [{"text": "a", "source": "s", "score": 0.9}], S, good_generate)["status"] == "skipped"


def test_followups_parse_and_cap():
    hits = [{"text": "a", "source": "s", "score": 0.9}]

    def gen(system, messages, s):
        return '{"questions": ["Why A?", "Why B?", "Why C?", "Why D?"]}'

    assert suggest_followups("q?", "answer", hits, S, gen) == ["Why A?", "Why B?", "Why C?"]


def test_followups_fail_open():
    hits = [{"text": "a", "source": "s", "score": 0.9}]
    assert suggest_followups("q?", "a", hits, S, broken_generate) == []


def test_first_json_tolerates_prose():
    assert _first_json('The data: {"supported": true, "unsupported": []}') == {
        "supported": True,
        "unsupported": [],
    }
    assert _first_json("no json here") is None


def test_env_flag_disables(monkeypatch):
    hits = [{"text": "a", "source": "s", "score": 0.9}]
    monkeypatch.setenv("VERIFY_ANSWERS", "0")
    assert verify_answer("x", hits, S, good_generate)["status"] == "skipped"
    monkeypatch.setenv("SUGGEST_FOLLOWUPS", "0")
    assert suggest_followups("q", "a", hits, S, good_generate) == []
    assert verification._env_flag("VERIFY_ANSWERS") is False
