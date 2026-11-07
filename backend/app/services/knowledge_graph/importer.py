from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_store import VectorStore
from app.crud.crud_knowledge_point import knowledge_point as crud_knowledge_point
from app.models.knowledge_external_ref import KnowledgeExternalRef
from app.models.knowledge_point import CATEGORY_NODE_TYPES, KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation, KnowledgeRelationType
from app.services.activity_logger import log_activity
from app.services.knowledge_graph.contracts import (
    CanonicalBundle,
    CanonicalKnowledgeNode,
    ImportAction,
    ImportPreview,
    ImportResult,
)
from app.services.knowledge_graph.matching import (
    category_external_id,
    chapter_key,
    domain_key,
    unique_slug,
)

SOURCE_NAME = "cn-math-taxonomy"
ENTITY_POINT = "knowledge_point"
ENTITY_RELATION = "knowledge_relation"


async def _fetch_refs(
    db: AsyncSession, *, entity_type: str
) -> Dict[str, KnowledgeExternalRef]:
    result = await db.execute(
        select(KnowledgeExternalRef).where(
            KnowledgeExternalRef.source == SOURCE_NAME,
            KnowledgeExternalRef.entity_type == entity_type,
        )
    )
    return {ref.external_id: ref for ref in result.scalars().all()}


def _index_points(points: List[KnowledgePoint]) -> Dict[Tuple[Optional[int], str, Optional[str]], List[KnowledgePoint]]:
    index: Dict[Tuple[Optional[int], str, Optional[str]], List[KnowledgePoint]] = defaultdict(list)
    for point in points:
        index[(point.parent_id, point.name, point.node_type)].append(point)
    return index


def _point_by_external(
    external_to_point: Dict[str, KnowledgePoint], external_id: str
) -> Optional[KnowledgePoint]:
    return external_to_point.get(external_id)


def _action_for(
    *,
    existing: Optional[KnowledgePoint],
    ambiguous: bool,
    update_existing: bool,
) -> str:
    if ambiguous:
        return "conflict"
    if existing is None:
        return "create"
    return "update" if update_existing else "link"


def _would_create_cycle(
    adjacency: Dict[int, List[int]], source_id: int, target_id: int
) -> bool:
    if source_id == target_id:
        return True
    seen: Set[int] = set()
    stack = [target_id]
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, ()))
    return False


class KnowledgeGraphImporter:
    async def preview(
        self,
        db: AsyncSession,
        *,
        bundle: CanonicalBundle,
        subject_id: int,
        checksum: str,
        update_existing: bool = False,
    ) -> ImportPreview:
        points = await crud_knowledge_point.get_by_subject(
            db, subject_id=subject_id, limit=None, include_categories=True
        )
        by_id = {p.id: p for p in points}
        point_refs = await _fetch_refs(db, entity_type=ENTITY_POINT)
        external_to_point: Dict[str, KnowledgePoint] = {
            external_id: by_id[ref.entity_id]
            for external_id, ref in point_refs.items()
            if ref.entity_id in by_id
        }
        category_index = _index_points(points)

        actions: List[ImportAction] = []
        errors: List[str] = []
        counts = defaultdict(int)

        domain_actions: Dict[str, Tuple[str, Optional[KnowledgePoint]]] = {}
        chapter_actions: Dict[str, Tuple[str, Optional[KnowledgePoint]]] = {}
        topic_actions: Dict[str, Tuple[str, Optional[KnowledgePoint]]] = {}

        domains = []
        chapters = []
        topics = []
        seen_domains = set()
        seen_chapters = set()
        for node in bundle.nodes:
            domain = (node.domain or "未分类").strip()
            if domain not in seen_domains:
                seen_domains.add(domain)
                domains.append(domain)
            if node.chapter:
                chapter = node.chapter.strip()
                key = chapter_key(domain, chapter)
                if key not in seen_chapters:
                    seen_chapters.add(key)
                    chapters.append((domain, chapter, key))
            topics.append(node)

        for domain in domains:
            ext = category_external_id(domain_key(domain))
            existing = _point_by_external(external_to_point, ext)
            ambiguous = False
            if existing is None:
                matches = category_index.get((None, domain, "domain"), [])
                if len(matches) > 1:
                    ambiguous = True
                elif matches:
                    existing = matches[0]
            action = _action_for(
                existing=existing, ambiguous=ambiguous, update_existing=update_existing
            )
            if action == "conflict":
                errors.append(f"领域「{domain}」存在多个同名节点，无法自动匹配")
            domain_actions[domain] = (action, existing)
            counts[action] += 1
            actions.append(
                ImportAction(
                    external_id=ext, name=domain, node_type="domain", action=action,
                    reason=None if action != "conflict" else "同名节点不唯一",
                )
            )

        for domain, chapter, key in chapters:
            ext = category_external_id(key)
            existing = _point_by_external(external_to_point, ext)
            ambiguous = False
            domain_action, domain_point = domain_actions.get(domain, ("create", None))
            parent_id = domain_point.id if domain_point else None
            if existing is None and domain_action != "create":
                matches = category_index.get((parent_id, chapter, "chapter"), [])
                if len(matches) > 1:
                    ambiguous = True
                elif matches:
                    existing = matches[0]
            action = _action_for(
                existing=existing, ambiguous=ambiguous, update_existing=update_existing
            )
            if action == "conflict":
                errors.append(f"章节「{chapter}」存在多个同名节点，无法自动匹配")
            chapter_actions[key] = (action, existing)
            counts[action] += 1
            actions.append(
                ImportAction(
                    external_id=ext, name=chapter, node_type="chapter", action=action,
                    reason=None if action != "conflict" else "同名节点不唯一",
                )
            )

        for node in topics:
            domain = (node.domain or "未分类").strip()
            key = chapter_key(domain, node.chapter.strip()) if node.chapter else None
            existing = _point_by_external(external_to_point, node.external_id)
            ambiguous = False
            parent_id = None
            parent_is_new = False
            if key:
                chapter_action, chapter_point = chapter_actions.get(key, ("create", None))
                parent_is_new = chapter_action == "create"
                parent_id = chapter_point.id if chapter_point else None
            else:
                domain_action, domain_point = domain_actions.get(domain, ("create", None))
                parent_is_new = domain_action == "create"
                parent_id = domain_point.id if domain_point else None

            if existing is None and not parent_is_new:
                matches = category_index.get((parent_id, node.name, node.node_type), [])
                if len(matches) > 1:
                    ambiguous = True
                elif matches:
                    existing = matches[0]

            action = _action_for(
                existing=existing, ambiguous=ambiguous, update_existing=update_existing
            )
            if action == "conflict":
                errors.append(f"知识点「{node.name}」存在多个同名节点，无法自动匹配")
            topic_actions[node.external_id] = (action, existing)
            counts[action] += 1
            actions.append(
                ImportAction(
                    external_id=node.external_id,
                    name=node.name,
                    node_type=node.node_type or "knowledge_point",
                    action=action,
                    reason=None if action != "conflict" else "同名节点不唯一",
                )
            )

        relation_refs = await _fetch_refs(db, entity_type=ENTITY_RELATION)
        relations_to_create = sum(
            1 for relation in bundle.relations
            if relation.external_id not in relation_refs
        )

        return ImportPreview(
            source=bundle.source,
            subject_id=subject_id,
            checksum=checksum,
            total_nodes=len(bundle.nodes),
            total_relations=len(bundle.relations),
            to_create=counts["create"],
            to_link=counts["link"],
            to_update=counts["update"],
            skipped=counts["skip"],
            conflicts=counts["conflict"],
            relations_to_create=relations_to_create,
            relations_skipped=len(bundle.relations) - relations_to_create,
            actions=actions,
            errors=errors,
        )

    async def apply(
        self,
        db: AsyncSession,
        *,
        bundle: CanonicalBundle,
        subject_id: int,
        checksum: str,
        user_id: Optional[int] = None,
        update_existing: bool = False,
    ) -> ImportResult:
        started = time.perf_counter()
        points = await crud_knowledge_point.get_by_subject(
            db, subject_id=subject_id, limit=None, include_categories=True
        )
        by_id = {p.id: p for p in points}
        point_refs = await _fetch_refs(db, entity_type=ENTITY_POINT)
        external_to_point: Dict[str, KnowledgePoint] = {
            external_id: by_id[ref.entity_id]
            for external_id, ref in point_refs.items()
            if ref.entity_id in by_id
        }
        category_index = _index_points(points)
        used_slugs: Set[str] = {p.slug for p in points}

        created_nodes = 0
        linked_nodes = 0
        updated_nodes = 0
        errors: List[str] = []

        domain_ids: Dict[str, int] = {}
        chapter_ids: Dict[str, int] = {}
        topic_ids: Dict[str, int] = {}
        new_topic_ids: List[int] = []

        def ensure_ref(entity_type: str, entity_id: int, external_id: str, raw: dict) -> None:
            ref = point_refs.get(external_id) if entity_type == ENTITY_POINT else None
            if ref is not None:
                ref.entity_id = entity_id
                return
            db.add(
                KnowledgeExternalRef(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source=SOURCE_NAME,
                    external_id=external_id,
                    raw=raw,
                )
            )

        try:
            domains = []
            seen_domains = set()
            chapters = []
            seen_chapters = set()
            for node in bundle.nodes:
                domain = (node.domain or "未分类").strip()
                if domain not in seen_domains:
                    seen_domains.add(domain)
                    domains.append(domain)
                if node.chapter:
                    key = chapter_key(domain, node.chapter.strip())
                    if key not in seen_chapters:
                        seen_chapters.add(key)
                        chapters.append((domain, node.chapter.strip(), key))

            for domain in domains:
                ext = category_external_id(domain_key(domain))
                existing = _point_by_external(external_to_point, ext)
                if existing is None:
                    matches = category_index.get((None, domain, "domain"), [])
                    if len(matches) == 1:
                        existing = matches[0]
                    elif len(matches) > 1:
                        raise ValueError(f"领域「{domain}」存在多个同名节点")
                if existing is None:
                    existing = KnowledgePoint(
                        name=domain,
                        slug=unique_slug(domain, used_slugs),
                        subject_id=subject_id,
                        parent_id=None,
                        node_type="domain",
                        source=SOURCE_NAME,
                    )
                    db.add(existing)
                    await db.flush()
                    created_nodes += 1
                else:
                    linked_nodes += 1
                ensure_ref(ENTITY_POINT, existing.id, ext, {"type": "domain", "name": domain})
                domain_ids[domain] = existing.id

            for domain, chapter, key in chapters:
                ext = category_external_id(key)
                existing = _point_by_external(external_to_point, ext)
                parent_id = domain_ids[domain]
                if existing is None:
                    matches = category_index.get((parent_id, chapter, "chapter"), [])
                    if len(matches) == 1:
                        existing = matches[0]
                    elif len(matches) > 1:
                        raise ValueError(f"章节「{chapter}」存在多个同名节点")
                if existing is None:
                    existing = KnowledgePoint(
                        name=chapter,
                        slug=unique_slug(chapter, used_slugs),
                        subject_id=subject_id,
                        parent_id=parent_id,
                        node_type="chapter",
                        chapter=chapter,
                        source=SOURCE_NAME,
                    )
                    db.add(existing)
                    await db.flush()
                    created_nodes += 1
                else:
                    linked_nodes += 1
                ensure_ref(ENTITY_POINT, existing.id, ext, {"type": "chapter", "name": chapter})
                chapter_ids[key] = existing.id

            for node in bundle.nodes:
                domain = (node.domain or "未分类").strip()
                parent_id = (
                    chapter_ids.get(chapter_key(domain, node.chapter.strip()))
                    if node.chapter else domain_ids.get(domain)
                )
                if parent_id is None:
                    raise ValueError(f"知识点「{node.name}」缺少父级分类")

                existing = _point_by_external(external_to_point, node.external_id)
                if existing is None:
                    matches = category_index.get((parent_id, node.name, node.node_type), [])
                    if len(matches) == 1:
                        existing = matches[0]
                    elif len(matches) > 1:
                        raise ValueError(f"知识点「{node.name}」存在多个同名节点")

                fields = {
                    "description": node.description,
                    "node_type": node.node_type,
                    "grade": node.grade,
                    "chapter": node.chapter,
                    "learning_requirement": node.learning_requirement,
                    "attributes": node.attributes,
                    "source": SOURCE_NAME,
                }
                if existing is None:
                    existing = KnowledgePoint(
                        name=node.name,
                        slug=unique_slug(node.name, used_slugs),
                        subject_id=subject_id,
                        parent_id=parent_id,
                        **fields,
                    )
                    db.add(existing)
                    await db.flush()
                    created_nodes += 1
                    new_topic_ids.append(existing.id)
                else:
                    linked_nodes += 1
                    if update_existing:
                        for field, value in fields.items():
                            if value is not None:
                                setattr(existing, field, value)
                        updated_nodes += 1

                ensure_ref(ENTITY_POINT, existing.id, node.external_id, node.raw)
                topic_ids[node.external_id] = existing.id

            relation_type_result = await db.execute(
                select(KnowledgeRelationType).where(
                    KnowledgeRelationType.code == "prerequisite"
                )
            )
            relation_type = relation_type_result.scalars().first()
            if not relation_type:
                raise ValueError("数据库缺少 prerequisite 关系类型")

            existing_relation_refs = await _fetch_refs(db, entity_type=ENTITY_RELATION)
            existing_relation_keys_result = await db.execute(
                select(
                    KnowledgeRelation.source_id,
                    KnowledgeRelation.target_id,
                    KnowledgeRelation.relation_type_id,
                ).where(KnowledgeRelation.subject_id == subject_id)
            )
            existing_relation_keys = {
                tuple(row) for row in existing_relation_keys_result.all()
            }

            existing_edge_rows = await db.execute(
                select(KnowledgeRelation.source_id, KnowledgeRelation.target_id).where(
                    KnowledgeRelation.subject_id == subject_id,
                    KnowledgeRelation.relation_type_id == relation_type.id,
                )
            )
            adjacency: Dict[int, List[int]] = defaultdict(list)
            for source_id, target_id in existing_edge_rows.all():
                adjacency[source_id].append(target_id)

            created_relations = 0
            skipped_relations = 0
            new_edges: List[Tuple[int, int]] = []
            pending: List[Tuple[KnowledgeRelation, str, Dict[str, Any]]] = []
            for relation in bundle.relations:
                source_id = topic_ids.get(relation.source_external_id)
                target_id = topic_ids.get(relation.target_external_id)
                if source_id is None or target_id is None:
                    errors.append(f"先修边端点缺失: {relation.external_id}")
                    continue
                key = (source_id, target_id, relation_type.id)
                if relation.external_id in existing_relation_refs or key in existing_relation_keys:
                    skipped_relations += 1
                    continue
                if _would_create_cycle(adjacency, source_id, target_id):
                    raise ValueError(f"先修关系存在环: {relation.external_id}")
                adjacency[source_id].append(target_id)
                relation_obj = KnowledgeRelation(
                    subject_id=subject_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type_id=relation_type.id,
                    description=relation.description,
                    source=SOURCE_NAME,
                    status="external",
                    attributes=relation.attributes,
                    created_by=user_id,
                    updated_by=user_id,
                )
                db.add(relation_obj)
                pending.append((relation_obj, relation.external_id, relation.raw))
                existing_relation_keys.add(key)
                new_edges.append((source_id, target_id))
                created_relations += 1

            await db.flush()
            for relation_obj, external_id, raw in pending:
                db.add(
                    KnowledgeExternalRef(
                        entity_type=ENTITY_RELATION,
                        entity_id=relation_obj.id,
                        source=SOURCE_NAME,
                        external_id=external_id,
                        raw=raw,
                    )
                )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ValueError(f"导入失败，违反数据库约束: {exc.orig}") from None
        except Exception:
            await db.rollback()
            raise

        vector_synced = False
        if new_topic_ids and VectorStore.is_available():
            try:
                items = []
                for point_id in new_topic_ids:
                    point = await crud_knowledge_point.get(db, point_id)
                    if not point:
                        continue
                    path_text = await crud_knowledge_point._build_path_text(db, point)
                    items.append({
                        "id": point.id,
                        "text": path_text,
                        "metadata": {
                            "id": point.id,
                            "subject_id": point.subject_id,
                            "name": point.name,
                            "slug": point.slug,
                        },
                    })
                VectorStore.upsert_knowledge_points_batch(items)
                vector_synced = True
            except Exception as exc:  # 向量化失败不阻塞导入
                errors.append(f"向量化失败，可稍后重建索引: {exc}")

        duration = round(time.perf_counter() - started, 2)
        try:
            await log_activity(
                db, user_id, "import", "knowledge_graph", None,
                details={
                    "source": bundle.source,
                    "subject_id": subject_id,
                    "checksum": checksum,
                    "created_nodes": created_nodes,
                    "linked_nodes": linked_nodes,
                    "created_relations": created_relations,
                },
            )
            await db.commit()
        except Exception:
            await db.rollback()

        return ImportResult(
            source=bundle.source,
            subject_id=subject_id,
            created_nodes=created_nodes,
            linked_nodes=linked_nodes,
            updated_nodes=updated_nodes,
            created_relations=created_relations,
            skipped_relations=skipped_relations,
            vector_synced=vector_synced,
            duration=duration,
            errors=errors,
        )


importer = KnowledgeGraphImporter()
