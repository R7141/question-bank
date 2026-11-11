import pytest
from sqlalchemy import select

from app.crud.crud_knowledge_external_ref import knowledge_external_ref
from app.crud.crud_knowledge_relation import knowledge_relation, relation_type_crud
from app.models.knowledge_external_ref import KnowledgeExternalRef
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation
from app.models.subject import Subject
from app.schemas.knowledge_graph import (
    KnowledgeRelationCreate,
    KnowledgeRelationTypeCreate,
    KnowledgeRelationTypeUpdate,
    KnowledgeRelationUpdate,
)


async def _seed_points(db_session):
    subject = Subject(name="数学", slug="math")
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)

    domain = KnowledgePoint(
        name="数与代数", slug="number-algebra", subject_id=subject.id, node_type="domain"
    )
    chapter = KnowledgePoint(
        name="一元二次方程", slug="quadratic-equation", subject_id=subject.id,
        node_type="chapter", parent_id=None,
    )
    a = KnowledgePoint(
        name="一元一次方程", slug="linear-equation", subject_id=subject.id,
        node_type="procedural", parent_id=chapter.id,
    )
    b = KnowledgePoint(
        name="一元二次方程", slug="quadratic-equation-topic", subject_id=subject.id,
        node_type="procedural", parent_id=chapter.id,
    )
    c = KnowledgePoint(
        name="二次函数", slug="quadratic-function", subject_id=subject.id,
        node_type="conceptual", parent_id=chapter.id,
    )
    db_session.add_all([domain, chapter, a, b, c])
    await db_session.commit()
    for obj in (domain, chapter, a, b, c):
        await db_session.refresh(obj)
    return subject, domain, chapter, a, b, c


async def _prerequisite_type(db_session):
    return await relation_type_crud.create(
        db_session,
        obj_in=KnowledgeRelationTypeCreate(
            code="prerequisite", name="先修", category="prerequisite", sort_order=10
        ),
    )


async def test_category_nodes_are_flagged(db_session):
    _, domain, chapter, a, _, _ = await _seed_points(db_session)

    assert domain.is_category is True
    assert chapter.is_category is True
    assert a.is_category is False


async def test_relation_create_derives_subject_and_direction(db_session):
    subject, _, _, a, b, _ = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)

    created = await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=a.id,
            target_id=b.id,
            relation_type_id=relation_type.id,
            description="学一元二次方程前先掌握一元一次方程",
            source="test",
            status="verified",
        ),
    )

    assert created.subject_id == subject.id
    assert created.source_id == a.id
    assert created.target_id == b.id
    assert created.status == "verified"


async def test_relation_rejects_self_loop(db_session):
    _, _, _, a, _, _ = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)

    with pytest.raises(ValueError, match="自身"):
        await knowledge_relation.create(
            db_session,
            obj_in=KnowledgeRelationCreate(
                source_id=a.id, target_id=a.id, relation_type_id=relation_type.id
            ),
        )


async def test_relation_rejects_category_endpoint(db_session):
    _, domain, _, a, _, _ = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)

    with pytest.raises(ValueError, match="分类节点"):
        await knowledge_relation.create(
            db_session,
            obj_in=KnowledgeRelationCreate(
                source_id=domain.id, target_id=a.id, relation_type_id=relation_type.id
            ),
        )


async def test_relation_rejects_cross_subject(db_session):
    _, _, _, a, _, _ = await _seed_points(db_session)
    other = Subject(name="物理", slug="physics")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_point = KnowledgePoint(name="力", slug="force", subject_id=other.id)
    db_session.add(other_point)
    await db_session.commit()
    await db_session.refresh(other_point)
    relation_type = await _prerequisite_type(db_session)

    with pytest.raises(ValueError, match="同一学科"):
        await knowledge_relation.create(
            db_session,
            obj_in=KnowledgeRelationCreate(
                source_id=a.id, target_id=other_point.id, relation_type_id=relation_type.id
            ),
        )


async def test_relation_rejects_duplicate_and_cycle(db_session):
    _, _, _, a, b, c = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)

    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=a.id, target_id=b.id, relation_type_id=relation_type.id
        ),
    )

    with pytest.raises(ValueError, match="已存在"):
        await knowledge_relation.create(
            db_session,
            obj_in=KnowledgeRelationCreate(
                source_id=a.id, target_id=b.id, relation_type_id=relation_type.id
            ),
        )

    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=b.id, target_id=c.id, relation_type_id=relation_type.id
        ),
    )

    with pytest.raises(ValueError, match="形成环"):
        await knowledge_relation.create(
            db_session,
            obj_in=KnowledgeRelationCreate(
                source_id=c.id, target_id=a.id, relation_type_id=relation_type.id
            ),
        )


async def test_get_for_point_direction_filters(db_session):
    _, _, _, a, b, c = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)

    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=a.id, target_id=b.id, relation_type_id=relation_type.id
        ),
    )
    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=b.id, target_id=c.id, relation_type_id=relation_type.id
        ),
    )

    outgoing = await knowledge_relation.get_for_point(db_session, point_id=b.id, direction="out")
    incoming = await knowledge_relation.get_for_point(db_session, point_id=b.id, direction="in")
    both = await knowledge_relation.get_for_point(db_session, point_id=b.id, direction="both")

    assert {(r.source_id, r.target_id) for r in outgoing} == {(b.id, c.id)}
    assert {(r.source_id, r.target_id) for r in incoming} == {(a.id, b.id)}
    assert len(both) == 2


async def test_relation_cascade_on_point_delete(db_session):
    _, _, _, a, b, _ = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)
    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=a.id, target_id=b.id, relation_type_id=relation_type.id
        ),
    )

    await db_session.delete(b)
    await db_session.commit()

    result = await db_session.execute(select(KnowledgeRelation))
    assert result.scalars().all() == []


async def test_external_ref_upsert_is_idempotent(db_session):
    _, _, _, a, _, _ = await _seed_points(db_session)
    first = await knowledge_external_ref.upsert(
        db_session,
        entity_type="knowledge_point",
        entity_id=a.id,
        source="cn-math-taxonomy",
        external_id="cnm_p001",
        payload_hash="hash-1",
    )
    second = await knowledge_external_ref.upsert(
        db_session,
        entity_type="knowledge_point",
        entity_id=a.id,
        source="cn-math-taxonomy",
        external_id="cnm_p001",
        payload_hash="hash-2",
    )

    assert first.id == second.id
    assert second.payload_hash == "hash-2"

    result = await db_session.execute(select(KnowledgeExternalRef))
    assert len(result.scalars().all()) == 1


async def test_relation_type_update_and_remove(db_session):
    relation_type = await _prerequisite_type(db_session)

    updated = await relation_type_crud.update(
        db_session,
        db_obj=relation_type,
        obj_in=KnowledgeRelationTypeUpdate(name="前置知识"),
    )
    assert updated.name == "前置知识"

    await relation_type_crud.remove(db_session, id=relation_type.id)
    assert await relation_type_crud.get(db_session, relation_type.id) is None


async def test_relation_type_cannot_be_deleted_while_in_use(db_session):
    _, _, _, a, b, _ = await _seed_points(db_session)
    relation_type = await _prerequisite_type(db_session)
    await knowledge_relation.create(
        db_session,
        obj_in=KnowledgeRelationCreate(
            source_id=a.id, target_id=b.id, relation_type_id=relation_type.id
        ),
    )

    with pytest.raises(ValueError, match="仍被"):
        await relation_type_crud.remove(db_session, id=relation_type.id)
