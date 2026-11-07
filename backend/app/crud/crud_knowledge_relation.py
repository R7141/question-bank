from typing import Any, Dict, List, Optional, Union

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.knowledge_point import CATEGORY_NODE_TYPES, KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation, KnowledgeRelationType
from app.schemas.knowledge_graph import (
    KnowledgeRelationCreate,
    KnowledgeRelationTypeCreate,
    KnowledgeRelationTypeUpdate,
    KnowledgeRelationUpdate,
)
from app.services.activity_logger import log_activity

PREREQUISITE_CODE = "prerequisite"


class CRUDKnowledgeRelationType(
    CRUDBase[KnowledgeRelationType, KnowledgeRelationTypeCreate, KnowledgeRelationTypeUpdate]
):
    async def get_by_code(self, db: AsyncSession, code: str) -> Optional[KnowledgeRelationType]:
        result = await db.execute(
            select(KnowledgeRelationType).where(KnowledgeRelationType.code == code)
        )
        return result.scalars().first()

    async def list_all(self, db: AsyncSession) -> List[KnowledgeRelationType]:
        result = await db.execute(
            select(KnowledgeRelationType).order_by(
                KnowledgeRelationType.sort_order, KnowledgeRelationType.id
            )
        )
        return list(result.scalars().all())

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        *,
        obj_in: KnowledgeRelationTypeCreate,
        user_id: Optional[int] = None,
    ) -> KnowledgeRelationType:
        if await self.get_by_code(db, obj_in.code):
            raise ValueError("关系类型 code 已存在")
        db_obj = KnowledgeRelationType(**obj_in.model_dump())
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        await log_activity(
            db, user_id, "create", "knowledge_relation_type", db_obj.id,
            details=obj_in.model_dump(),
        )
        await db.commit()
        return db_obj

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        *,
        db_obj: KnowledgeRelationType,
        obj_in: Union[KnowledgeRelationTypeUpdate, Dict[str, Any]],
        user_id: Optional[int] = None,
    ) -> KnowledgeRelationType:
        update_data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump(exclude_unset=True)
        if "code" in update_data and update_data["code"] != db_obj.code:
            existing = await self.get_by_code(db, update_data["code"])
            if existing and existing.id != db_obj.id:
                raise ValueError("关系类型 code 已存在")
        updated = await super().update(db, db_obj=db_obj, obj_in=obj_in)
        await log_activity(
            db, user_id, "update", "knowledge_relation_type", updated.id, details=update_data,
        )
        await db.commit()
        return updated

    async def remove(  # type: ignore[override]
        self, db: AsyncSession, *, id: int, user_id: Optional[int] = None
    ) -> KnowledgeRelationType:
        obj = await self.get(db, id)
        if obj:
            await db.delete(obj)
            await db.commit()
            await log_activity(db, user_id, "delete", "knowledge_relation_type", id)
            await db.commit()
        return obj


class CRUDKnowledgeRelation(
    CRUDBase[KnowledgeRelation, KnowledgeRelationCreate, KnowledgeRelationUpdate]
):
    @staticmethod
    def _detail_options():
        return (
            selectinload(KnowledgeRelation.relation_type),
            selectinload(KnowledgeRelation.source_point),
            selectinload(KnowledgeRelation.target_point),
        )

    async def get_detail(self, db: AsyncSession, relation_id: int) -> Optional[KnowledgeRelation]:
        result = await db.execute(
            select(KnowledgeRelation)
            .options(*self._detail_options())
            .where(KnowledgeRelation.id == relation_id)
        )
        return result.scalars().first()

    async def get_for_point(
        self,
        db: AsyncSession,
        *,
        point_id: int,
        direction: str = "both",
        relation_type_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[KnowledgeRelation]:
        if direction == "out":
            condition = KnowledgeRelation.source_id == point_id
        elif direction == "in":
            condition = KnowledgeRelation.target_id == point_id
        else:
            condition = or_(
                KnowledgeRelation.source_id == point_id,
                KnowledgeRelation.target_id == point_id,
            )

        query = select(KnowledgeRelation).options(*self._detail_options()).where(condition)
        if relation_type_id is not None:
            query = query.where(KnowledgeRelation.relation_type_id == relation_type_id)
        query = query.order_by(KnowledgeRelation.id).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def _get_active_type(
        self, db: AsyncSession, relation_type_id: int
    ) -> KnowledgeRelationType:
        relation_type = await db.get(KnowledgeRelationType, relation_type_id)
        if not relation_type:
            raise ValueError("关系类型不存在")
        if not relation_type.is_active:
            raise ValueError("关系类型已停用")
        return relation_type

    async def _validate_endpoints(
        self,
        db: AsyncSession,
        *,
        source_id: int,
        target_id: int,
        subject_id: Optional[int],
    ) -> tuple[KnowledgePoint, KnowledgePoint, int]:
        if source_id == target_id:
            raise ValueError("关系不能指向自身")

        source = await db.get(KnowledgePoint, source_id)
        target = await db.get(KnowledgePoint, target_id)
        if not source or not target:
            raise ValueError("关系的起点或终点知识点不存在")

        if source.node_type in CATEGORY_NODE_TYPES or target.node_type in CATEGORY_NODE_TYPES:
            raise ValueError("分类节点不能参与知识关系")

        if source.subject_id != target.subject_id:
            raise ValueError("关系两端必须属于同一学科")

        if subject_id is not None and subject_id != source.subject_id:
            raise ValueError("关系学科与知识点学科不一致")

        return source, target, source.subject_id

    async def _would_create_cycle(
        self, db: AsyncSession, *, subject_id: int, source_id: int, target_id: int
    ) -> bool:
        """添加 source -> target 的先修边是否形成环。"""
        relation_type = await relation_type_crud.get_by_code(db, PREREQUISITE_CODE)
        if not relation_type:
            return False

        visited: set[int] = set()
        queue: List[int] = [target_id]
        while queue:
            current = queue.pop(0)
            if current == source_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            result = await db.execute(
                select(KnowledgeRelation.target_id).where(
                    KnowledgeRelation.subject_id == subject_id,
                    KnowledgeRelation.source_id == current,
                    KnowledgeRelation.relation_type_id == relation_type.id,
                )
            )
            queue.extend(result.scalars().all())
        return False

    async def _assert_unique(
        self,
        db: AsyncSession,
        *,
        subject_id: int,
        source_id: int,
        target_id: int,
        relation_type_id: int,
        exclude_id: Optional[int] = None,
    ) -> None:
        query = select(KnowledgeRelation.id).where(
            KnowledgeRelation.subject_id == subject_id,
            KnowledgeRelation.source_id == source_id,
            KnowledgeRelation.target_id == target_id,
            KnowledgeRelation.relation_type_id == relation_type_id,
        )
        if exclude_id is not None:
            query = query.where(KnowledgeRelation.id != exclude_id)
        result = await db.execute(query)
        if result.scalars().first() is not None:
            raise ValueError("相同关系已存在")

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        *,
        obj_in: KnowledgeRelationCreate,
        user_id: Optional[int] = None,
        check_cycle: bool = True,
    ) -> KnowledgeRelation:
        source, _target, subject_id = await self._validate_endpoints(
            db, source_id=obj_in.source_id, target_id=obj_in.target_id,
            subject_id=obj_in.subject_id,
        )
        relation_type = await self._get_active_type(db, obj_in.relation_type_id)
        await self._assert_unique(
            db,
            subject_id=subject_id,
            source_id=obj_in.source_id,
            target_id=obj_in.target_id,
            relation_type_id=obj_in.relation_type_id,
        )
        if check_cycle and relation_type.code == PREREQUISITE_CODE:
            if await self._would_create_cycle(
                db, subject_id=subject_id,
                source_id=obj_in.source_id, target_id=obj_in.target_id,
            ):
                raise ValueError("先修关系不能形成环")

        data = obj_in.model_dump()
        data["subject_id"] = subject_id
        db_obj = KnowledgeRelation(**data)
        if user_id:
            db_obj.created_by = user_id
            db_obj.updated_by = user_id
        db.add(db_obj)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ValueError("相同关系已存在或违反约束") from None
        await db.refresh(db_obj)
        await log_activity(
            db, user_id, "create", "knowledge_relation", db_obj.id,
            details={
                "subject_id": subject_id,
                "source_id": obj_in.source_id,
                "target_id": obj_in.target_id,
                "relation_type_id": obj_in.relation_type_id,
            },
        )
        await db.commit()
        return db_obj

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        *,
        db_obj: KnowledgeRelation,
        obj_in: Union[KnowledgeRelationUpdate, Dict[str, Any]],
        user_id: Optional[int] = None,
    ) -> KnowledgeRelation:
        update_data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump(exclude_unset=True)
        if user_id:
            db_obj.updated_by = user_id

        if "relation_type_id" in update_data:
            relation_type = await self._get_active_type(db, update_data["relation_type_id"])
            await self._assert_unique(
                db,
                subject_id=db_obj.subject_id,
                source_id=db_obj.source_id,
                target_id=db_obj.target_id,
                relation_type_id=update_data["relation_type_id"],
                exclude_id=db_obj.id,
            )
            if relation_type.code == PREREQUISITE_CODE:
                if await self._would_create_cycle(
                    db, subject_id=db_obj.subject_id,
                    source_id=db_obj.source_id, target_id=db_obj.target_id,
                ):
                    raise ValueError("先修关系不能形成环")

        updated = await super().update(db, db_obj=db_obj, obj_in=obj_in)
        await log_activity(
            db, user_id, "update", "knowledge_relation", updated.id, details=update_data,
        )
        await db.commit()
        return updated

    async def remove(  # type: ignore[override]
        self, db: AsyncSession, *, id: int, user_id: Optional[int] = None
    ) -> KnowledgeRelation:
        obj = await self.get(db, id)
        if obj:
            await db.delete(obj)
            await db.commit()
            await log_activity(db, user_id, "delete", "knowledge_relation", id)
            await db.commit()
        return obj


relation_type_crud = CRUDKnowledgeRelationType(KnowledgeRelationType)
knowledge_relation = CRUDKnowledgeRelation(KnowledgeRelation)
