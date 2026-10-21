from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.import_task import ImportTask
from app.models.user import User
from app.services.doc_processor import doc_processor
from app.services.mineru import MinerUConfigurationError, MinerUError


async def _auth_headers(db_session) -> dict[str, str]:
    user = User(
        username="pdf-importer",
        full_name="PDF Importer",
        hashed_password=get_password_hash("s3cret"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def test_upload_pdf_returns_review_drafts(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    headers = await _auth_headers(db_session)

    async def fake_process_pdf(file_path, **kwargs):
        return {
            "task_id": kwargs["task_id"],
            "content": "# 1+1",
            "questions": [
                {
                    "q_type": "free_response",
                    "content": "1 + 1 = ?",
                    "answer": "2",
                    "difficulty": 1,
                }
            ],
            "paper": None,
        }

    monkeypatch.setattr(doc_processor, "process_pdf", fake_process_pdf)

    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "# 1+1"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["content"]["type"] == "doc"
    assert body["file_path"].endswith("paper.pdf")


async def test_upload_pdf_rejects_non_pdf(client, db_session):
    headers = await _auth_headers(db_session)
    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.docx", b"fake", "application/vnd.openxmlformats")},
    )
    assert response.status_code == 400


async def test_upload_pdf_maps_mineru_errors(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    headers = await _auth_headers(db_session)

    async def missing_config(file_path, **kwargs):
        raise MinerUConfigurationError("未配置 MinerU")

    monkeypatch.setattr(doc_processor, "process_pdf", missing_config)
    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 503
    assert "未配置 MinerU" in response.json()["detail"]

    async def conversion_failed(file_path, **kwargs):
        raise MinerUError("MinerU 转换超时")

    monkeypatch.setattr(doc_processor, "process_pdf", conversion_failed)
    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 502
    assert "转换超时" in response.json()["detail"]


async def test_batch_import_accepts_pdf(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    headers = await _auth_headers(db_session)

    response = await client.post(
        "/api/v1/imports?mode=extract",
        headers=headers,
        files={"files": ("paper.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    task = (
        await db_session.execute(
            select(ImportTask).where(ImportTask.id == body[0]["id"])
        )
    ).scalar_one()
    assert task.file_type == "pdf"
    assert task.status.value == "pending"
