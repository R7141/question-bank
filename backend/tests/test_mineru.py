import io
import zipfile
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.importing.ingest import PdfIngestor
from app.services.mineru import (
    MinerUClient,
    MinerUConfigurationError,
    MinerUError,
)


def _zip_bytes(markdown: str = "# 题目\n\n![图](images/a.jpg)\n") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("markdown.md", markdown)
        archive.writestr("images/a.jpg", b"fake-image")
    return buffer.getvalue()


def _client(handler, *, poll_interval: float = 0.2) -> MinerUClient:
    return MinerUClient(
        base_url="http://mineru.test:8000",
        poll_interval=poll_interval,
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture
def upload_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path / "media")
    return tmp_path


async def test_parse_pdf_submits_polls_and_downloads_zip(upload_dirs):
    pdf_path = upload_dirs / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")
    result_zip = _zip_bytes()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.method == "POST" and request.url.path == "/v1/tasks":
            return httpx.Response(202, json={"task_id": "remote-1", "status": "queued"})
        if request.url.path == "/v1/tasks/remote-1":
            return httpx.Response(200, json={"task_id": "remote-1", "status": "completed"})
        if request.url.path == "/v1/tasks/remote-1/result":
            return httpx.Response(
                200,
                content=result_zip,
                headers={"content-type": "application/zip"},
            )
        return httpx.Response(404)

    result = await _client(handler).parse_pdf(pdf_path, task_id="local-1")

    assert result.zip_path == settings.UPLOAD_DIR / "local-1" / "mineru_result.zip"
    assert result.zip_path.read_bytes() == result_zip
    assert calls[0][0] == "POST"
    assert "tier=standard" in calls[0][2]
    assert "output_formats=markdown" in calls[0][2]
    assert "output_formats=zip" in calls[0][2]


async def test_pdf_ingestor_extracts_markdown_and_rewrites_images(upload_dirs):
    pdf_path = upload_dirs / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")
    result_zip = _zip_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tasks":
            return httpx.Response(202, json={"task_id": "remote-2"})
        if request.url.path == "/v1/tasks/remote-2":
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path == "/v1/tasks/remote-2/result":
            return httpx.Response(
                200, content=result_zip, headers={"content-type": "application/zip"}
            )
        return httpx.Response(404)

    doc = await PdfIngestor(_client(handler)).ingest(
        pdf_path, task_id="local-2", filename="paper.pdf"
    )

    assert "![图](/static/media/local-2/images/a.jpg)" in doc.markdown
    assert (settings.MEDIA_DIR / "local-2" / "images" / "a.jpg").read_bytes() == b"fake-image"
    assert (settings.UPLOAD_DIR / "local-2" / "content.md").exists()


async def test_parse_pdf_falls_back_to_inline_json_markdown(upload_dirs):
    pdf_path = upload_dirs / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tasks":
            return httpx.Response(202, json={"task_id": "remote-3"})
        if request.url.path == "/v1/tasks/remote-3":
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path == "/v1/tasks/remote-3/result":
            return httpx.Response(
                200,
                json={"content": {"markdown": "# inline markdown"}},
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404)

    result = await _client(handler).parse_pdf(pdf_path, task_id="local-3")

    assert result.zip_path is None
    assert result.markdown == "# inline markdown"


async def test_parse_pdf_reports_failed_task(upload_dirs):
    pdf_path = upload_dirs / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tasks":
            return httpx.Response(202, json={"task_id": "remote-4"})
        if request.url.path == "/v1/tasks/remote-4":
            return httpx.Response(
                200, json={"status": "failed", "error": "model crashed"}
            )
        return httpx.Response(404)

    with pytest.raises(MinerUError, match="model crashed"):
        await _client(handler).parse_pdf(pdf_path, task_id="local-4")


async def test_parse_pdf_requires_configuration(upload_dirs):
    pdf_path = upload_dirs / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")

    with pytest.raises(MinerUConfigurationError):
        await MinerUClient(base_url="").parse_pdf(pdf_path, task_id="local-5")


async def test_cancel_task_calls_mineru_delete():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "canceled"})

    await _client(handler).cancel_task("remote-9")
    assert calls == [("DELETE", "/v1/tasks/remote-9")]
