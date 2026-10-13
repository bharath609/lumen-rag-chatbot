import pytest

from src.chunking import chunk_text, chunk_pages


def test_short_text_single_chunk():
    assert chunk_text("hello world", 100, 10) == ["hello world"]


def test_long_text_overlaps_and_covers_everything():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, 200, 40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert chunks[0].startswith("word0")
    assert chunks[-1].endswith("word499")


def test_overlap_must_be_smaller():
    with pytest.raises(ValueError):
        chunk_text("abc", 10, 10)


def test_terminates_on_unbroken_text():
    assert len(chunk_text("x" * 5000, 300, 50)) > 1


def test_chunk_pages_keeps_metadata():
    out = chunk_pages([{"text": "a " * 400, "source": "f.pdf", "page": 3}], 200, 20)
    assert all(c["source"] == "f.pdf" and c["page"] == 3 for c in out)
    assert [c["chunk"] for c in out] == list(range(len(out)))
