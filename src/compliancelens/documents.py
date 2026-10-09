import hashlib
import io
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, model_validator
from pypdf import PdfReader

from compliancelens.config import Settings

HOSTS = {
    "OSFI": {"www.osfi-bsif.gc.ca", "osfi-bsif.gc.ca"},
    "FINTRAC": {"fintrac-canafe.canada.ca"},
    "OPC": {"www.priv.gc.ca", "priv.gc.ca"},
}
USER_AGENT = "ComplianceLens/0.1 (non-commercial public-document research)"


class Source(BaseModel):
    document_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    regulator: Literal["OSFI", "FINTRAC", "OPC"]
    title: str = Field(min_length=1)
    source_url: str
    format: Literal["html", "pdf"]
    public: Literal[True]
    retrieved_at: str | None = None
    sha256: str | None = None
    resolved_url: str | None = None

    @model_validator(mode="after")
    def validate_official_source(self) -> "Source":
        check_source_url(self.source_url, self.regulator)
        if self.resolved_url:
            check_source_url(self.resolved_url, self.regulator)
        return self


@dataclass(frozen=True)
class Section:
    heading: str
    text: str
    anchor: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    content_hash: str
    text: str
    regulator: str
    document_title: str
    section_heading: str
    page: int | None
    anchor: str | None
    source_url: str
    retrieved_at: str


def check_source_url(url: str, regulator: str) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in HOSTS[regulator]
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
    ):
        raise ValueError("Document URLs must be public HTTPS URLs on the regulator's official host")


def load_manifest(path: Path) -> tuple[dict, list[Source]]:
    manifest = json.loads(path.read_text())
    sources = [Source.model_validate(item) for item in manifest["documents"]]
    if not sources:
        raise ValueError("Manifest must contain at least one public document")
    if len({item.document_id for item in sources}) != len(sources):
        raise ValueError("Manifest contains duplicate document IDs")
    return manifest, sources


def fetch_public(
    client: httpx.Client,
    url: str,
    regulator: str,
    can_fetch: Callable[[str], bool] | None = None,
) -> tuple[bytes, str]:
    for _ in range(5):
        check_source_url(url, regulator)
        if can_fetch is not None and not can_fetch(url):
            raise ValueError("Redirect target is not permitted by the reviewed robots policy")
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            response.raise_for_status()
            body = bytearray()
            for part in response.iter_bytes():
                body.extend(part)
                if len(body) > 20_000_000:
                    raise ValueError("Public document exceeds the 20 MB download limit")
            return bytes(body), url
    raise ValueError("Too many redirects for a public document")


def download_sources(path: Path, raw_dir: Path, refresh: bool = False) -> list[Source]:
    manifest, sources = load_manifest(path)
    raw_dir.mkdir(parents=True, exist_ok=True)
    robots: dict[str, RobotFileParser] = {}
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        for source in sources:
            target = raw_dir / f"{source.document_id}.{source.format}"
            if not refresh and target.exists() and source.sha256 and source.retrieved_at:
                if hashlib.sha256(target.read_bytes()).hexdigest() != source.sha256:
                    raise ValueError("Cached source hash mismatch; refresh the official download")
                continue
            parts = urlsplit(source.source_url)
            host = parts.hostname
            if host not in robots:
                parser = RobotFileParser()
                robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
                response = client.get(robots_url, follow_redirects=False)
                if response.status_code == 404:
                    parser.parse([])
                else:
                    response.raise_for_status()
                    if response.is_redirect:
                        raise ValueError("robots.txt redirect requires review before downloading")
                    parser.parse(response.text.splitlines())
                robots[host] = parser
            if not robots[host].can_fetch(USER_AGENT, source.source_url):
                raise ValueError(f"robots.txt disallows manifest document {source.document_id}")
            time.sleep(max(1, robots[host].crawl_delay(USER_AGENT) or 0))
            content, resolved = fetch_public(
                client,
                source.source_url,
                source.regulator,
                lambda url, host=host: (
                    urlsplit(url).hostname == host and robots[host].can_fetch(USER_AGENT, url)
                ),
            )
            if source.format == "pdf" and not content.startswith(b"%PDF"):
                raise ValueError("Expected a PDF from the official source")
            target.write_bytes(content)
            source.sha256 = hashlib.sha256(content).hexdigest()
            source.retrieved_at = datetime.now(UTC).isoformat()
            source.resolved_url = resolved
            manifest["documents"] = [item.model_dump() for item in sources]
            path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return sources


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_html(content: bytes) -> list[Section]:
    soup = BeautifulSoup(content, "html.parser")
    main = soup.select_one("main")
    if not main:
        raise ValueError("Official HTML source has no main content landmark")
    for element in main.select("script, style, nav, header, footer, form, aside, .toc, .wb-toc"):
        element.decompose()
    body = main.select_one(".field--name-body") or main
    sections: list[Section] = []
    heading, anchor, blocks = "Overview", None, []
    for element in body.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li", "tr"]):
        if element.name in {"p", "li"} and element.find_parent(["li", "tr"]):
            continue
        text = clean_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if element.name.startswith("h"):
            if blocks:
                sections.append(Section(heading, "\n\n".join(blocks), anchor))
            heading, blocks = text, []
            parent = element.parent if isinstance(element.parent, Tag) else None
            anchor = element.get("id") or (parent.get("id") if parent else None)
        else:
            blocks.append(text)
    if blocks:
        sections.append(Section(heading, "\n\n".join(blocks), anchor))
    if not sections:
        raise ValueError("No regulatory text was parsed from the public HTML source")
    return sections


def parse_document(source: Source, raw_dir: Path) -> list[Section]:
    content = (raw_dir / f"{source.document_id}.{source.format}").read_bytes()
    if hashlib.sha256(content).hexdigest() != source.sha256 or not source.retrieved_at:
        raise ValueError("Document needs a verified download and retrieval date before parsing")
    if source.format == "html":
        return parse_html(content)
    reader = PdfReader(io.BytesIO(content))
    sections = [
        Section(f"Page {number}", page.extract_text() or "", page=number)
        for number, page in enumerate(reader.pages, 1)
    ]
    if not any(section.text.strip() for section in sections):
        raise ValueError("PDF has no extractable text; OCR is not implemented")
    return [section for section in sections if section.text.strip()]


def make_chunks(source: Source, sections: list[Section], settings: Settings) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size_bytes,
        chunk_overlap=settings.chunk_overlap_bytes,
        length_function=lambda text: len(text.encode("utf-8")),
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    for section_number, section in enumerate(sections):
        for part_number, text in enumerate(splitter.split_text(section.text)):
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            identifier = f"{source.document_id}:{section_number}:{part_number}"
            chunks.append(
                Chunk(
                    id=hashlib.sha256(identifier.encode()).hexdigest(),
                    document_id=source.document_id,
                    content_hash=content_hash,
                    text=text,
                    regulator=source.regulator,
                    document_title=source.title,
                    section_heading=section.heading,
                    page=section.page,
                    anchor=str(section.anchor) if section.anchor else None,
                    source_url=source.resolved_url or source.source_url,
                    retrieved_at=source.retrieved_at or "",
                )
            )
    return chunks
