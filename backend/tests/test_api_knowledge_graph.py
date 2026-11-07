from app.core.security import create_access_token
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelationType
from app.models.subject import Subject
from app.models.subject_member import SubjectMember
from app.models.user import User

API = "/api/v1"


async def _seed_user(db_session, *, username, is_superuser=False) -> User:
    user = User(
        username=username, full_name=username, hashed_password="x",
        is_active=True, is_superuser=is_superuser,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_subject(db_session, *, name, slug) -> Subject:
    subject = Subject(name=name, slug=slug)
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)
    return subject


async def _grant(db_session, *, user, subject, role) -> None:
    db_session.add(SubjectMember(user_id=user.id, subject_id=subject.id, role=role))
    await db_session.commit()


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def _seed_relation_type(db_session) -> KnowledgeRelationType:
    relation_type = KnowledgeRelationType(
        code="prerequisite", name="先修", category="prerequisite", sort_order=10
    )
    db_session.add(relation_type)
    await db_session.commit()
    await db_session.refresh(relation_type)
    return relation_type


async def _seed_points(db_session, subject):
    domain = KnowledgePoint(
        name="数与代数", slug="number-algebra", subject_id=subject.id, node_type="domain"
    )
    db_session.add(domain)
    await db_session.commit()
    await db_session.refresh(domain)

    chapter = KnowledgePoint(
        name="方程", slug="equation", subject_id=subject.id, node_type="chapter",
        parent_id=domain.id,
    )
    db_session.add(chapter)
    await db_session.commit()
    await db_session.refresh(chapter)

    a = KnowledgePoint(
        name="一元一次方程", slug="linear-equation", subject_id=subject.id,
        node_type="procedural", parent_id=chapter.id,
    )
    b = KnowledgePoint(
        name="一元二次方程", slug="quadratic-equation-topic", subject_id=subject.id,
        node_type="procedural", parent_id=chapter.id,
    )
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)
    return domain, chapter, a, b


async def _ctx(db_session):
    admin = await _seed_user(db_session, username="admin", is_superuser=True)
    manager = await _seed_user(db_session, username="manager")
    viewer = await _seed_user(db_session, username="viewer")
    math = await _seed_subject(db_session, name="数学", slug="math")
    physics = await _seed_subject(db_session, name="物理", slug="physics")
    await _grant(db_session, user=manager, subject=math, role="manager")
    await _grant(db_session, user=viewer, subject=math, role="viewer")
    domain, chapter, a, b = await _seed_points(db_session, math)
    physics_point = KnowledgePoint(
        name="力", slug="force", subject_id=physics.id, node_type="conceptual"
    )
    db_session.add(physics_point)
    await db_session.commit()
    await db_session.refresh(physics_point)
    relation_type = await _seed_relation_type(db_session)
    return {
        "admin": admin, "manager": manager, "viewer": viewer,
        "math": math, "physics": physics,
        "domain": domain, "chapter": chapter, "a": a, "b": b,
        "physics_point": physics_point, "relation_type": relation_type,
    }


def _relation_payload(source_id, target_id, relation_type_id, **kwargs):
    payload = {
        "source_id": source_id,
        "target_id": target_id,
        "relation_type_id": relation_type_id,
        "description": "先修关系",
        "source": "manual",
        "status": "verified",
    }
    payload.update(kwargs)
    return payload


async def test_manager_can_create_relation_and_read_it(client, db_session):
    ctx = await _ctx(db_session)
    payload = _relation_payload(ctx["a"].id, ctx["b"].id, ctx["relation_type"].id)

    created = await client.post(
        f"{API}/knowledge-relations", json=payload, headers=_auth(ctx["manager"])
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["source_id"] == ctx["a"].id
    assert body["target_id"] == ctx["b"].id
    assert body["subject_id"] == ctx["math"].id

    listed = await client.get(
        f"{API}/knowledge-points/{ctx['a'].id}/relations",
        headers=_auth(ctx["viewer"]),
    )
    assert listed.status_code == 200, listed.text
    relations = listed.json()
    assert len(relations) == 1
    assert relations[0]["source_point"]["name"] == "一元一次方程"
    assert relations[0]["target_point"]["name"] == "一元二次方程"
    assert relations[0]["relation_type"]["code"] == "prerequisite"


async def test_viewer_cannot_create_relation(client, db_session):
    ctx = await _ctx(db_session)
    payload = _relation_payload(ctx["a"].id, ctx["b"].id, ctx["relation_type"].id)

    resp = await client.post(
        f"{API}/knowledge-relations", json=payload, headers=_auth(ctx["viewer"])
    )
    assert resp.status_code == 403


async def test_category_and_cross_subject_are_rejected(client, db_session):
    ctx = await _ctx(db_session)

    category = await client.post(
        f"{API}/knowledge-relations",
        json=_relation_payload(ctx["domain"].id, ctx["a"].id, ctx["relation_type"].id),
        headers=_auth(ctx["manager"]),
    )
    assert category.status_code == 400

    cross_subject = await client.post(
        f"{API}/knowledge-relations",
        json=_relation_payload(ctx["a"].id, ctx["physics_point"].id, ctx["relation_type"].id),
        headers=_auth(ctx["manager"]),
    )
    assert cross_subject.status_code == 422


async def test_self_loop_and_duplicate_are_rejected(client, db_session):
    ctx = await _ctx(db_session)
    headers = _auth(ctx["manager"])

    self_loop = await client.post(
        f"{API}/knowledge-relations",
        json=_relation_payload(ctx["a"].id, ctx["a"].id, ctx["relation_type"].id),
        headers=headers,
    )
    assert self_loop.status_code == 400

    payload = _relation_payload(ctx["a"].id, ctx["b"].id, ctx["relation_type"].id)
    first = await client.post(f"{API}/knowledge-relations", json=payload, headers=headers)
    assert first.status_code == 200
    duplicate = await client.post(f"{API}/knowledge-relations", json=payload, headers=headers)
    assert duplicate.status_code == 400


async def test_update_and_delete_relation(client, db_session):
    ctx = await _ctx(db_session)
    headers = _auth(ctx["manager"])
    created = await client.post(
        f"{API}/knowledge-relations",
        json=_relation_payload(ctx["a"].id, ctx["b"].id, ctx["relation_type"].id),
        headers=headers,
    )
    relation_id = created.json()["id"]

    updated = await client.put(
        f"{API}/knowledge-relations/{relation_id}",
        json={"description": "更新后的说明", "status": "verified"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "更新后的说明"

    deleted = await client.delete(
        f"{API}/knowledge-relations/{relation_id}", headers=headers
    )
    assert deleted.status_code == 200

    missing = await client.get(
        f"{API}/knowledge-relations/{relation_id}", headers=headers
    )
    assert missing.status_code == 404


async def test_relation_type_management_requires_superuser(client, db_session):
    ctx = await _ctx(db_session)

    listed = await client.get(
        f"{API}/knowledge-relation-types", headers=_auth(ctx["viewer"])
    )
    assert listed.status_code == 200
    assert [t["code"] for t in listed.json()] == ["prerequisite"]

    forbidden = await client.post(
        f"{API}/knowledge-relation-types",
        json={"code": "related", "name": "关联"},
        headers=_auth(ctx["manager"]),
    )
    assert forbidden.status_code == 400

    created = await client.post(
        f"{API}/knowledge-relation-types",
        json={"code": "related", "name": "关联"},
        headers=_auth(ctx["admin"]),
    )
    assert created.status_code == 200, created.text
    assert created.json()["code"] == "related"


async def test_vector_status_excludes_category_nodes(client, db_session):
    ctx = await _ctx(db_session)

    resp = await client.get(
        f"{API}/knowledge-points/vector-status?subject_id={ctx['math'].id}",
        headers=_auth(ctx["admin"]),
    )
    assert resp.status_code == 200, resp.text
    # 2 个真实知识点；domain/chapter 不计入向量索引。
    assert resp.json()["db_count"] == 2


async def test_vector_status_uses_subject_scoped_vector_count(client, db_session, monkeypatch):
    from app.core.vector_store import VectorStore

    ctx = await _ctx(db_session)
    monkeypatch.setattr(VectorStore, "is_available", classmethod(lambda cls: True))
    monkeypatch.setattr(VectorStore, "count", classmethod(lambda cls, name="knowledge_points": 99))
    monkeypatch.setattr(
        VectorStore, "count_by_subject",
        classmethod(lambda cls, subject_id, name="knowledge_points": 2),
    )

    resp = await client.get(
        f"{API}/knowledge-points/vector-status?subject_id={ctx['math'].id}",
        headers=_auth(ctx["admin"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["db_count"] == 2
    assert body["vector_count"] == 2
    assert body["needs_reindex"] is False
