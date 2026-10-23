import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.import_task import SMART_IMPORT_SOURCE, ImportTask, ImportTaskStatus
from app.models.user import User


async def _auth_user(db_session) -> tuple[User, dict[str, str]]:
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
    return user, {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def test_upload_pdf_creates_async_task(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "MINERU_API_URL", "http://mineru.test:8000")
    user, headers = await _auth_user(db_session)

    response = await client.post(
        "/api/v1/upload/pdf?subject_id=7&method=ai",
        headers=headers,
        files={"file": ("paper.pdf", b"%PDF-1.7 fake", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["stage"] == "queued"
    assert body["task_id"]

    task = (
        await db_session.execute(
            select(ImportTask).where(ImportTask.id == body["task_id"])
        )
    ).scalar_one()
    assert task.source == SMART_IMPORT_SOURCE
    assert task.user_id == user.id
    assert task.file_type == "pdf"
    assert task.subject_id == 7
    assert task.method == "ai"
    assert task.content_sha256
    assert task.result_path is None


async def test_upload_pdf_rejects_non_pdf(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "MINERU_API_URL", "http://mineru.test:8000")
    _user, headers = await _auth_user(db_session)
    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.docx", b"fake", "application/vnd.openxmlformats")},
    )
    assert response.status_code == 400


async def test_upload_pdf_requires_mineru_config(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "MINERU_API_URL", "")
    _user, headers = await _auth_user(db_session)
    response = await client.post(
        "/api/v1/upload/pdf",
        headers=headers,
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 503
    assert "MinerU" in response.json()["detail"]


async def test_smart_import_result_returns_stored_payload(
    client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    user, headers = await _auth_user(db_session)
    result_path = tmp_path / "result.json"
    payload = {
        "task_id": "local-1",
        "content": "# 1+1",
        "questions": [{"q_type": "free_response", "content": "1 + 1"}],
        "paper": None,
        "file_path": "/tmp/paper.pdf",
    }
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    task = ImportTask(
        user_id=user.id,
        description="PDF 智能导入 paper.pdf",
        source=SMART_IMPORT_SOURCE,
        file_path="/tmp/paper.pdf",
        original_filename="paper.pdf",
        file_type="pdf",
        subject_id=1,
        method="ai",
        stage="completed",
        status=ImportTaskStatus.COMPLETED,
        content_sha256="a" * 64,
        result_path=str(result_path),
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    response = await client.get(
        f"/api/v1/imports/{task.id}/result", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "# 1+1"
    assert body["questions"][0]["content"] == "1 + 1"
    assert body["content_sha256"] == "a" * 64
    assert body["duplicate_of"] is None


async def test_smart_import_result_not_ready(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    user, headers = await _auth_user(db_session)
    task = ImportTask(
        user_id=user.id,
        description="PDF 智能导入 paper.pdf",
        source=SMART_IMPORT_SOURCE,
        file_path="/tmp/paper.pdf",
        original_filename="paper.pdf",
        file_type="pdf",
        stage="mineru",
        status=ImportTaskStatus.PROCESSING,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    response = await client.get(
        f"/api/v1/imports/{task.id}/result", headers=headers
    )
    assert response.status_code == 409


async def test_batch_import_accepts_pdf(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    _user, headers = await _auth_user(db_session)

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
