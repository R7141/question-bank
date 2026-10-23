import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.import_task import (
    SMART_IMPORT_SOURCE,
    ImportTask,
    ImportTaskStatus,
)
from app.models.question import Question
from app.models.user import User
from app.services.doc_processor import doc_processor
from app import worker


async def test_worker_smart_pdf_stores_review_result_without_importing(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.setattr(settings, "MINERU_WORKER_TIMEOUT_SECONDS", 1800)

    user = User(
        username="smart-pdf-worker",
        full_name="Smart PDF Worker",
        hashed_password=get_password_hash("s3cret"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")

    task = ImportTask(
        user_id=user.id,
        description="PDF 智能导入 paper.pdf",
        source=SMART_IMPORT_SOURCE,
        file_path=str(pdf_path),
        original_filename="paper.pdf",
        file_type="pdf",
        mode="extract",
        method="ai",
        subject_id=3,
        stage="queued",
        status=ImportTaskStatus.PENDING,
        content_sha256="b" * 64,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    async def fake_process_pdf(file_path, **kwargs):
        await kwargs["on_submitted"]("job-123")
        await kwargs["on_ingested"]()
        assert kwargs["subject_id"] == 3
        assert kwargs["method"] == "ai"
        return {
            "task_id": kwargs["task_id"],
            "content": "# 题目",
            "questions": [
                {
                    "q_type": "free_response",
                    "content": "1 + 1 = ?",
                    "answer": "2",
                    "difficulty": 1,
                }
            ],
            "paper": {"suggested_title": "测试卷", "outline": []},
        }

    monkeypatch.setattr(doc_processor, "process_pdf", fake_process_pdf)

    await worker.process_task(db_session, task)
    await db_session.refresh(task)

    assert task.status == ImportTaskStatus.COMPLETED
    assert task.stage == "completed"
    assert task.remote_task_id == "job-123"
    assert task.result_path
    result = json.loads(Path(task.result_path).read_text(encoding="utf-8"))
    assert result["content"] == "# 题目"
    assert result["questions"][0]["content"]["type"] == "doc"
    assert result["paper"]["suggested_title"] == "测试卷"
    assert result["content_sha256"] == "b" * 64

    questions = (await db_session.execute(select(Question))).scalars().all()
    assert questions == []


async def test_worker_marks_smart_pdf_failure(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path / "media")

    user = User(
        username="smart-pdf-fail",
        full_name="Smart PDF Fail",
        hashed_password=get_password_hash("s3cret"),
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 fake")
    task = ImportTask(
        user_id=user.id,
        description="PDF 智能导入 paper.pdf",
        source=SMART_IMPORT_SOURCE,
        file_path=str(pdf_path),
        original_filename="paper.pdf",
        file_type="pdf",
        method="ai",
        stage="queued",
        status=ImportTaskStatus.PENDING,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    async def fake_process_pdf(*args, **kwargs):
        raise RuntimeError("MinerU 转换失败")

    monkeypatch.setattr(doc_processor, "process_pdf", fake_process_pdf)

    await worker.process_task(db_session, task)
    await db_session.refresh(task)

    assert task.status == ImportTaskStatus.FAILED
    assert task.stage == "failed"
    assert "MinerU" in (task.error_message or "")
