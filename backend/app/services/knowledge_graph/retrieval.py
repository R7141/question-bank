"""Knowledge graph retrieval for AI context.

Vector search finds candidate knowledge points; this service adds node
descriptions and one-hop semantic relations so the model can distinguish
facts (graph edges) from its own inference.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.vector_store import VectorStore
from app.models.knowledge_point import CATEGORY_NODE_TYPES, KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation, KnowledgeRelationType

logger = logging.getLogger(__name__)

CONTEXT_RELATION_CODES = (
    "prerequisite",
    "related",
    "derived_from",
    "applied_to",
    "uses",
)


class KnowledgeGraphContextService:
    async def build(
        self,
        db: AsyncSession,
        *,
        query: str,
        subject_id: Optional[int] = None,
        limit: int = 5,
        relation_limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """Vector recall + graph context. Returns None when unavailable."""
        if not VectorStore.is_available():
            return None
        try:
            results = await asyncio.to_thread(
                VectorStore.search_similar,
                query=query,
                subject_id=subject_id,
                limit=limit,
            )
        except Exception as exc:  # 图谱/向量失败不阻塞主流程
            logger.warning("Knowledge graph vector search failed: %s", exc)
            return None

        if not results or not results.get("ids") or not results["ids"][0]:
            return None

        ids: List[int] = []
        for raw_id in results["ids"][0]:
            try:
                ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
        if not ids:
            return None

        documents = results.get("documents", [[]])[0]
        path_by_id = {
            int(raw_id): document
            for raw_id, document in zip(results["ids"][0], documents)
            if str(raw_id).isdigit()
        }
        nodes = await self._load_nodes(db, ids=ids, subject_id=subject_id)
        relations = await self._load_relations(
            db, ids=[n.id for n in nodes], subject_id=subject_id,
            limit=relation_limit,
        )
        text = self._format(nodes, relations, path_by_id=path_by_id)
        return {
            "ids": [n.id for n in nodes],
            "nodes": nodes,
            "relations": relations,
            "text": text,
        }

    async def context_for_ids(
        self,
        db: AsyncSession,
        *,
        ids: List[int],
        subject_id: Optional[int] = None,
        relation_limit: int = 12,
    ) -> Optional[str]:
        if not ids or not VectorStore.is_available():
            return None
        nodes = await self._load_nodes(db, ids=ids, subject_id=subject_id)
        if not nodes:
            return None
        relations = await self._load_relations(
            db, ids=[n.id for n in nodes], subject_id=subject_id,
            limit=relation_limit,
        )
        return self._format(nodes, relations)

    async def _load_nodes(
        self, db: AsyncSession, *, ids: List[int], subject_id: Optional[int]
    ) -> List[KnowledgePoint]:
        query = select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
        if subject_id is not None:
            query = query.where(KnowledgePoint.subject_id == subject_id)
        result = await db.execute(query)
        by_id = {
            point.id: point
            for point in result.scalars().all()
            if point.node_type not in CATEGORY_NODE_TYPES
        }
        return [by_id[i] for i in ids if i in by_id]

    async def _load_relations(
        self,
        db: AsyncSession,
        *,
        ids: List[int],
        subject_id: Optional[int],
        limit: int,
    ) -> List[KnowledgeRelation]:
        if not ids:
            return []
        type_result = await db.execute(
            select(KnowledgeRelationType.id).where(
                KnowledgeRelationType.code.in_(CONTEXT_RELATION_CODES)
            )
        )
        type_ids = list(type_result.scalars().all())
        if not type_ids:
            return []

        query = (
            select(KnowledgeRelation)
            .options(
                selectinload(KnowledgeRelation.relation_type),
                selectinload(KnowledgeRelation.source_point),
                selectinload(KnowledgeRelation.target_point),
            )
            .where(
                KnowledgeRelation.relation_type_id.in_(type_ids),
                or_(
                    KnowledgeRelation.source_id.in_(ids),
                    KnowledgeRelation.target_id.in_(ids),
                ),
            )
        )
        if subject_id is not None:
            query = query.where(KnowledgeRelation.subject_id == subject_id)
        query = query.order_by(KnowledgeRelation.id).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    def _format(
        self,
        nodes: List[KnowledgePoint],
        relations: List[KnowledgeRelation],
        *,
        path_by_id: Optional[Dict[int, str]] = None,
    ) -> str:
        path_by_id = path_by_id or {}
        lines: List[str] = [
            "以下为知识图谱中的事实（external 状态表示外部导入且可能未审核，仅作参考）："
        ]
        for node in nodes:
            path = path_by_id.get(node.id) or node.chapter or ""
            suffix = f"，{path}" if path else ""
            lines.append(f"- [{node.id}] {node.name}{suffix}")
            if node.description:
                lines.append(f"  描述：{node.description}")

        if relations:
            lines.append("关系：")
            for relation in relations:
                type_name = relation.relation_type.name if relation.relation_type else "关系"
                source_name = relation.source_point.name if relation.source_point else str(relation.source_id)
                target_name = relation.target_point.name if relation.target_point else str(relation.target_id)
                strength = (relation.attributes or {}).get("strength")
                meta = f"{strength}，" if strength else ""
                lines.append(
                    f"- {type_name}：{source_name} -> {target_name}"
                    f"（{meta}{relation.status}）"
                )
        return "\n".join(lines)


graph_context = KnowledgeGraphContextService()
