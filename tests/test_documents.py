import hashlib
import io
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter

from compliancelens.config import Settings
from compliancelens.documents import (
    Section,
    Source,
    fetch_public,
    make_chunks,
    parse_document,
    parse_html,
)


def source(**overrides) -> Source:
    return Source.model_validate(
        {
            "document_id": "osfi-test",
            "regulator": "OSFI",
            "title": "Test guideline",
            "source_url": "https://www.osfi-bsif.gc.ca/en/test",
            "format": "html",
            "public": True,
            "retrieved_at": "2026-10-08T12:00:00Z",
            **overrides,
        }
    )


def test_sections_keep_anchors_and_exclude_navigation() -> None:
    sections = parse_html(b"""<main><nav><p>MENU</p></nav><h1>Test guideline</h1>
    <h2 id='governance'>Governance</h2><p>Boards oversee risk.</p>
    <ul><li>Train employees.<p>Keep training records.</p></li></ul>
    <h2 id='review'>Review</h2><p>Review each year.</p>
    <footer><p>FOOTER</p></footer></main>""")
    assert [item.heading for item in sections] == ["Governance", "Review"]
    assert sections[0].anchor == "governance"
    assert sections[0].text.count("Keep training records.") == 1
    assert "MENU" not in sections[0].text
    assert "FOOTER" not in sections[-1].text


def test_missing_main_is_an_error() -> None:
    with pytest.raises(ValueError, match="main content"):
        parse_html(b"<h1>Access denied</h1>")


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_url": "https://evil.example/test"},
        {"public": False},
        {"document_id": "../../secrets"},
        {"source_url": "http://www.osfi-bsif.gc.ca/en/test"},
    ],
)
def test_manifest_rejects_unapproved_sources(overrides: dict) -> None:
    with pytest.raises(ValueError):
        source(**overrides)


def test_redirect_is_validated_before_following() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/secret"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="official host"):
            fetch_public(client, source().source_url, "OSFI")
    assert len(calls) == 1


def test_redirect_to_disallowed_official_path_is_not_fetched() -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "/blocked"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="robots policy"):
            fetch_public(
                client, source().source_url, "OSFI", lambda url: not url.endswith("/blocked")
            )
    assert len(calls) == 1


def test_unicode_chunk_byte_limit_and_provenance() -> None:
    settings = Settings(_env_file=".env.example", chunk_size_bytes=256, chunk_overlap_bytes=32)
    chunks = make_chunks(
        source(), [Section("Accountability", "éthique " * 100, "account", 2)], settings
    )
    assert len(chunks) > 1
    assert all(len(chunk.text.encode()) <= 256 for chunk in chunks)
    assert all(chunk.page == 2 and chunk.anchor == "account" for chunk in chunks)
    assert all(chunk.document_title == "Test guideline" for chunk in chunks)
    assert (
        make_chunks(source(), [Section("Accountability", "éthique " * 100, "account", 2)], settings)
        == chunks
    )


def test_parser_refuses_modified_download(tmp_path: Path) -> None:
    (tmp_path / "osfi-test.html").write_bytes(b"changed")
    with pytest.raises(ValueError, match="verified download"):
        parse_document(source(sha256="not-the-hash"), tmp_path)


def test_image_only_pdf_is_not_silently_ingested(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    content = buffer.getvalue()
    (tmp_path / "osfi-test.pdf").write_bytes(content)
    with pytest.raises(ValueError, match="OCR"):
        parse_document(source(format="pdf", sha256=hashlib.sha256(content).hexdigest()), tmp_path)
