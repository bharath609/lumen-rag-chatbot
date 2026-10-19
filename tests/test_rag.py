from src.config import Settings
from src.rag import NO_ANSWER, answer


class FakeStore:
    def __init__(self, hits):
        self.hits = hits
        self.last_sources = None

    def query(self, q, k, sources=None):
        self.last_sources = sources
        return self.hits


def fake_llm(system, messages, s):
    return "Answer using " + messages[-1]["content"].split("\n")[1][:20]


S = Settings()


def test_no_hits_skips_llm():
    called = []
    r = answer("q", FakeStore([]), S, llm_fn=lambda *a: called.append(1))
    assert r["answer"] == NO_ANSWER and not called
    assert r["citations"] == []
    assert r["metrics"]["llm_called"] is False


def test_low_score_filtered():
    store = FakeStore([{"text": "x", "source": "a.txt", "page": None, "score": 0.01}])
    assert answer("q", store, S, llm_fn=fake_llm)["answer"] == NO_ANSWER


def test_good_hit_returns_answer_and_sources():
    store = FakeStore([{"text": "Paris is the capital.", "source": "a.txt", "page": 2, "score": 0.9}])
    r = answer("capital?", store, S, llm_fn=fake_llm)
    assert r["sources"][0]["source"] == "a.txt" and r["answer"].startswith("Answer")
    assert r["citations"][0]["index"] == 1
    assert r["citations"][0]["page"] == 2
    assert r["metrics"]["used_chunks"] == 1
    assert r["metrics"]["top_score"] == 0.9


def test_sources_filter_passed_to_store():
    store = FakeStore([{"text": "x", "source": "a.txt", "page": None, "score": 0.9}])
    answer("q", store, S, llm_fn=fake_llm, sources=["a.txt"])
    assert store.last_sources == ["a.txt"]
    store = FakeStore([{"text": "x", "source": "a.txt", "page": None, "score": 0.9}])
    answer("q", store, S, llm_fn=fake_llm)
    assert store.last_sources is None
