"""上传文件内容完全一致的历史导入提示。

仅提示、不阻塞;近似重复不在范围内。智能导入的结果查询需要排除当前任务自身,
因此把旧的 upload.py 私有 helper 抽成共享服务。
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.composition import Composition
from app.models.import_task import ImportTask, ImportTaskStatus


async def attach_duplicate_hint(
    result: dict[str, Any],
    db: AsyncSession,
    *,
    content: Optional[bytes] = None,
    digest: Optional[str] = None,
    exclude_task_id: Optional[int] = None,
) -> dict[str, Any]:
    """标记“与历史导入文件内容完全一致”。只提示,不阻塞。"""
    digest = digest or (hashlib.sha256(content).hexdigest() if content else None)
    result["content_sha256"] = digest
    if not digest:
        result["duplicate_of"] = None
        return result

    conditions = [
        ImportTask.content_sha256 == digest,
        ImportTask.status == ImportTaskStatus.COMPLETED,
    ]
    if exclude_task_id is not None:
        conditions.append(ImportTask.id != exclude_task_id)

    task = (
        await db.execute(
            select(ImportTask)
            .where(*conditions)
            .order_by(ImportTask.created_at.desc())
        )
    ).scalars().first()
    if task is None:
        result["duplicate_of"] = None
        return result

    comp = (
        await db.execute(
            select(Composition).where(Composition.source_import_task_id == task.id)
        )
    ).scalars().first()
    result["duplicate_of"] = {
        "import_task_id": task.id,
        "original_filename": task.original_filename,
        "imported_at": task.created_at.isoformat() if task.created_at else None,
        "composition_id": comp.id if comp else None,
    }
    return result
