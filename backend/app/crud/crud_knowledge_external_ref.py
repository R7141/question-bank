from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.knowledge_external_ref import KnowledgeExternalRef
from app.schemas.knowledge_graph import KnowledgeExternalRefCreate


class CRUDKnowledgeExternalRef(
    CRUDBase[KnowledgeExternalRef, KnowledgeExternalRefCreate, KnowledgeExternalRefCreate]
):
    async def get_by_external(
        self,
        db: AsyncSession,
        *,
        source: str,
        entity_type: str,
        external_id: str,
    ) -> Optional[KnowledgeExternalRef]:
        result = await db.execute(
            select(KnowledgeExternalRef).where(
                KnowledgeExternalRef.source == source,
                KnowledgeExternalRef.entity_type == entity_type,
                KnowledgeExternalRef.external_id == external_id,
            )
        )
        return result.scalars().first()

    async def list_for_entity(
        self, db: AsyncSession, *, entity_type: str, entity_id: int
    ) -> List[KnowledgeExternalRef]:
        result = await db.execute(
            select(KnowledgeExternalRef).where(
                KnowledgeExternalRef.entity_type == entity_type,
                KnowledgeExternalRef.entity_id == entity_id,
            )
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        db: AsyncSession,
        *,
        entity_type: str,
        entity_id: int,
        source: str,
        external_id: str,
        external_version: Optional[str] = None,
        payload_hash: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> KnowledgeExternalRef:
        existing = await self.get_by_external(
            db, source=source, entity_type=entity_type, external_id=external_id
        )
        if existing:
            existing.entity_id = entity_id
            existing.external_version = external_version
            existing.payload_hash = payload_hash
            existing.raw = raw
            db.add(existing)
            ref = existing
        else:
            ref = KnowledgeExternalRef(
                entity_type=entity_type,
                entity_id=entity_id,
                source=source,
                external_id=external_id,
                external_version=external_version,
                payload_hash=payload_hash,
                raw=raw,
            )
            db.add(ref)
        if commit:
            await db.commit()
            await db.refresh(ref)
        else:
            await db.flush()
        return ref

    async def delete_for_entity(
        self, db: AsyncSession, *, entity_type: str, entity_id: int, commit: bool = True
    ) -> None:
        refs = await self.list_for_entity(db, entity_type=entity_type, entity_id=entity_id)
        for ref in refs:
            await db.delete(ref)
        if commit:
            await db.commit()


knowledge_external_ref = CRUDKnowledgeExternalRef(KnowledgeExternalRef)
