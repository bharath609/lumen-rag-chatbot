from src.loaders import load_file


def test_text_markdown_csv_html_and_json_loaders(tmp_path):
    (tmp_path / "note.txt").write_text("hello\nworld", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Heading\nBody", encoding="utf-8")
    (tmp_path / "rows.csv").write_text("name,score\nAda,10", encoding="utf-8")
    (tmp_path / "page.html").write_text(
        "<h1>Title</h1><script>ignore me</script><p>Visible text</p>",
        encoding="utf-8",
    )
    (tmp_path / "data.json").write_text('{"answer": 42}', encoding="utf-8")

    assert load_file(tmp_path / "note.txt")[0]["text"] == "hello\nworld"
    assert load_file(tmp_path / "notes.md")[0]["source"] == "notes.md"
    assert "Ada\t10" in load_file(tmp_path / "rows.csv")[0]["text"]
    html_text = load_file(tmp_path / "page.html")[0]["text"]
    assert "Visible text" in html_text and "ignore me" not in html_text
    assert '"answer": 42' in load_file(tmp_path / "data.json")[0]["text"]


def test_loader_preserves_explicit_source_for_temporary_files(tmp_path):
    path = tmp_path / "temporary.txt"
    path.write_text("content", encoding="utf-8")

    page = load_file(path, source="uploaded.txt")[0]

    assert page["source"] == "uploaded.txt"
    assert page["page"] is None


def test_plain_text_and_code_extensions_share_the_text_loader(tmp_path):
    path = tmp_path / "pipeline.py"
    path.write_text("def answer(question):\n    return question", encoding="utf-8")

    pages = load_file(path)

    assert pages == [
        {
            "text": "def answer(question):\n    return question",
            "source": "pipeline.py",
            "page": None,
        }
    ]


def test_unsupported_extension_is_clear(tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"not a supported document")

    try:
        load_file(path)
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:  # pragma: no cover - assertion helper for a deliberately failing test
        raise AssertionError("unsupported files must be rejected")
