import asyncio
import logging
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession

# Add backend directory to path so we can import app modules
sys.path.append(str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.core.config import get_db_url, is_configured, settings
from app.models.import_task import (
    BATCH_IMPORT_SOURCE,
    SMART_IMPORT_SOURCE,
    ImportTask,
    ImportTaskStatus,
)
from app.models.question import QuestionStatus
from app.models.user import User
from app.services.doc_processor import doc_processor
from app.services.embedding import reload_embedding_function
from app.services.importing.contracts import ImportDefaults
from app.services.importing.normalize import question_importer
from app.services.importing.review import extracted_to_v2_review
from app.services.mineru import MinerUClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TaskCancelled(Exception):
    """用户取消后用于中止智能导入流程。"""


async def _process_smart_pdf_task(
    db: AsyncSession,
    task: ImportTask,
    *,
    file_path: Path,
    subject_id: int | None,
) -> None:
    """MinerU + AI 抽取,但只保存可复核结果,不直接入题库。"""
    proc_task_id = str(task.id)

    async def on_submitted(remote_task_id: str) -> None:
        task.remote_task_id = remote_task_id
        await db.commit()
        await db.refresh(task)
        if task.status == ImportTaskStatus.CANCELLED:
            await MinerUClient().cancel_task(remote_task_id)
            raise TaskCancelled()

    async def on_ingested() -> None:
        await db.refresh(task)
        if task.status == ImportTaskStatus.CANCELLED:
            raise TaskCancelled()
        task.stage = "extracting"
        task.updated_at = datetime.now(timezone.utc)
        await db.commit()

    result = await doc_processor.process_pdf(
        file_path,
        db=db,
        task_id=proc_task_id,
        mode=task.mode or "extract",
        method=task.method or "ai",
        subject_id=subject_id,
        timeout=settings.MINERU_WORKER_TIMEOUT_SECONDS,
        on_submitted=on_submitted,
        on_ingested=on_ingested,
    )

    await db.refresh(task)
    if task.status == ImportTaskStatus.CANCELLED:
        raise TaskCancelled()

    questions = extracted_to_v2_review(
        result.get("questions", []), subject_id=subject_id
    )
    payload = {
        "task_id": result.get("task_id") or proc_task_id,
        "content": result.get("content", ""),
        "questions": questions,
        "paper": result.get("paper"),
        "file_path": task.file_path,
        "content_sha256": task.content_sha256,
    }

    result_dir = settings.UPLOAD_DIR / str(task.id)
    result_path = result_dir / "extraction.json"
    await asyncio.to_thread(result_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        result_path.write_text,
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    task.result_path = str(result_path)
    task.result_summary = json.dumps(
        {"count": len(questions), "proc_task_id": payload["task_id"]}
    )
    task.stage = "completed"
    task.status = ImportTaskStatus.COMPLETED
    logger.info(
        "Smart PDF task %s completed. %d questions ready for review.",
        task.id,
        len(questions),
    )


async def process_task(db: AsyncSession, task: ImportTask):
    try:
        logger.info(f"Starting task {task.id} ({task.file_type}): {task.original_filename}")

        task.status = ImportTaskStatus.PROCESSING
        if task.source == SMART_IMPORT_SOURCE:
            task.stage = "mineru"
        task.updated_at = datetime.now(timezone.utc)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        logger.info(f"Task {task.id} status updated to PROCESSING")

        file_path = Path(task.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Smart imports carry an explicit subject; batch imports keep the old
        # behaviour of falling back to the user's last active subject.
        subject_id = task.subject_id if task.source == SMART_IMPORT_SOURCE else None
        if subject_id is None and task.user_id:
            user_stmt = select(User).where(User.id == task.user_id)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user:
                subject_id = user.last_active_subject_id

        if task.source == SMART_IMPORT_SOURCE:
            if task.file_type != "pdf":
                raise RuntimeError(f"Unsupported smart import type: {task.file_type}")
            await _process_smart_pdf_task(
                db, task, file_path=file_path, subject_id=subject_id
            )
            return

        result = None
        if task.file_type == 'docx':
            import uuid
            proc_task_id = str(uuid.uuid4())
            result = await doc_processor.process_docx(file_path, db=db, task_id=proc_task_id, mode=task.mode or "extract", subject_id=subject_id)
        elif task.file_type == 'pdf':
            import uuid
            proc_task_id = str(uuid.uuid4())
            result = await doc_processor.process_pdf(
                file_path,
                db=db,
                task_id=proc_task_id,
                mode=task.mode or "extract",
                subject_id=subject_id,
                timeout=settings.MINERU_WORKER_TIMEOUT_SECONDS,
            )
        elif task.file_type == 'markdown':
            content = file_path.read_text(encoding='utf-8')
            import uuid
            proc_task_id = str(uuid.uuid4())
            result = await doc_processor.process_markdown(content, db=db, filename=task.original_filename, task_id=proc_task_id, mode=task.mode or "extract", subject_id=subject_id)

        if result:
            # Save questions via the shared importer (same path as /questions/batch-legacy).
            questions_data = result.get("questions", [])
            defaults = ImportDefaults(
                subject_id=subject_id,
                status=QuestionStatus.PENDING,
                source=task.original_filename,
            )
            report = await question_importer.import_batch(
                db,
                questions_data,
                user_id=task.user_id,
                import_task_id=task.id,
                defaults=defaults,
            )

            task.result_summary = json.dumps(
                {
                    "count": report.saved_count,
                    "failed": report.failed_count,
                    "proc_task_id": result.get("task_id"),
                }
            )
            task.status = ImportTaskStatus.COMPLETED
            logger.info(
                f"Task {task.id} completed. Saved {report.saved_count} questions, "
                f"{report.failed_count} skipped (un-adaptable)."
            )
        else:
            task.status = ImportTaskStatus.FAILED
            task.error_message = "No result from processor"
            logger.error(f"Task {task.id} failed: No result")

    except TaskCancelled:
        logger.info("Task %s was cancelled; stopping smart import.", task.id)
        await db.refresh(task)
        if task.status != ImportTaskStatus.CANCELLED:
            task.status = ImportTaskStatus.CANCELLED
        task.stage = "cancelled"
    except Exception as e:
        logger.error(f"Error processing task {task.id}: {e}", exc_info=True)
        await db.refresh(task)
        if task.status == ImportTaskStatus.CANCELLED:
            logger.info("Task %s was cancelled; ignoring processing error.", task.id)
            return
        task.status = ImportTaskStatus.FAILED
        task.error_message = str(e)
        if task.source == SMART_IMPORT_SOURCE:
            task.stage = "failed"

        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            logger.critical("Quota exceeded (429), stopping worker...")
            raise SystemExit(1)
    finally:
        task.updated_at = datetime.now(timezone.utc)
        await db.commit()


async def wait_for_schema() -> None:
    """Block until the database schema has been migrated.

    ``is_configured()`` only tells us a database URL exists — the tables may not
    be there yet because migrations run in a *different* process (the backend
    entrypoint / the setup wizard) and can still be in progress. Probing a core
    table here prevents the worker from querying (and erroring on) tables that
    have not been created yet.
    """
    while True:
        try:
            async with SessionLocal() as db:
                await db.execute(text("SELECT 1 FROM import_tasks LIMIT 1"))
            return
        except Exception:
            logger.info("Worker: waiting for database schema (migrations)...")
            await asyncio.sleep(5)


async def worker():
    logger.info("Worker started, initializing...")

    # In a packaged desktop build the worker is spawned before the first-run
    # setup wizard has picked a database. Wait until the app is configured
    # before touching the DB or the embedding model.
    while not is_configured():
        logger.info("Worker: database not configured yet, waiting for setup...")
        await asyncio.sleep(5)

    # A configured URL does not guarantee the schema exists yet: migrations may
    # still be running in another process. Wait for the tables before touching
    # the DB or the embedding model (which reads ``system_settings``).
    await wait_for_schema()

    # Initialize Embedding Function
    try:
        await reload_embedding_function()
        logger.info("Embedding function initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize embedding function: {e}")

    logger.info("Worker waiting for tasks...")
    # SQLite does not support ``SELECT ... FOR UPDATE SKIP LOCKED``. In the
    # single-writer SQLite (desktop) case there is only one worker anyway, so
    # row-level locking is unnecessary; on MySQL we keep SKIP LOCKED so multiple
    # workers can pull tasks concurrently without contention.
    use_row_lock = not get_db_url().startswith("sqlite")
    while True:
        async with SessionLocal() as db:
            try:
                # SKIP LOCKED query
                stmt = select(ImportTask).where(
                    ImportTask.status == ImportTaskStatus.PENDING,
                    ImportTask.source.in_([BATCH_IMPORT_SOURCE, SMART_IMPORT_SOURCE]),
                )\
                    .order_by(ImportTask.created_at)\
                    .limit(1)
                if use_row_lock:
                    stmt = stmt.with_for_update(skip_locked=True)
                
                result = await db.execute(stmt)
                task = result.scalar_one_or_none()
                
                if task:
                    await process_task(db, task)
                else:
                    await db.commit()
                    await asyncio.sleep(10)
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(5)

def main():
    """Blocking entry point. Importable so the packaged desktop launcher can run
    the worker in a child process (see the packaging plan)."""
    asyncio.run(worker())


if __name__ == "__main__":
    main()
