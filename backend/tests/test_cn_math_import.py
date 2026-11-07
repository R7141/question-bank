import hashlib
import io
import json
import zipfile

from sqlalchemy import select

from app.core.security import create_access_token
from app.models.knowledge_external_ref import KnowledgeExternalRef
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation, KnowledgeRelationType
from app.models.subject import Subject
from app.models.user import User
from app.services.knowledge_graph.adapters.cn_math_taxonomy import CnMathTaxonomyAdapter
from app.services.knowledge_graph.contracts import CanonicalBundle
from app.services.knowledge_graph.importer import importer

API = "/api/v1"

TOPICS = [
    {
        "id": "cnm_p001",
        "name": "1到5各数的认识",
        "domain": "数与代数",
        "grade": 1,
        "semester": "上",
        "chapter": "一年级上册 第1单元 5以内数的认识",
        "type": "conceptual",
        "description": "认识 1 到 5。",
        "mastery_criteria": ["能数出 1 到 5"],
        "diagnostic_question": {"question": "3 的后面是几？", "answer": "4"},
        "external": False,
        "standards": [],
    },
    {
        "id": "cnm_p002",
        "name": "5以内数的大小",
        "domain": "数与代数",
        "grade": 1,
        "semester": "上",
        "chapter": "一年级上册 第1单元 5以内数的认识",
        "type": "procedural",
        "description": "会比较 5 以内的数。",
        "mastery_criteria": [],
        "diagnostic_question": {"question": "4 和 2 哪个大？", "answer": "4"},
        "external": False,
        "standards": [{"id": "cms-2022:1.NA.02", "confidence": "exact"}],
    },
    {
        "id": "cnm_p003",
        "name": "数的比较",
        "domain": "数与代数",
        "grade": 1,
        "semester": "上",
        "chapter": "一年级上册 第2单元 数的比较",
        "type": "reasoning",
        "description": "用大于、小于、等于比较数。",
        "mastery_criteria": [],
        "diagnostic_question": {"question": "5 和 3 哪个大？", "answer": "5"},
        "external": False,
        "standards": [],
    },
    {
        "id": "cne_p001",
        "name": "英语字母表",
        "subject": "english",
        "domain": "语音",
        "grade": 3,
        "semester": "上",
        "chapter": "三年级上册 Unit 1",
        "type": "procedural",
        "description": "认读 26 个字母。",
        "mastery_criteria": [],
        "diagnostic_question": {"question": "字母表有多少个字母？", "answer": "26"},
        "external": False,
        "standards": [],
    },
]

DEPENDENCIES = [
    {
        "topicId": "cnm_p002",
        "prerequisiteId": "cnm_p001",
        "strength": "hard",
        "reason": "学大小比较前先认识 1 到 5。",
    },
    {
        "topicId": "cnm_p003",
        "prerequisiteId": "cnm_p002",
        "strength": "soft",
        "reason": "比较数的大小有助于学习数的比较。",
    },
    {
        "topicId": "cne_p001",
        "prerequisiteId": "cne_p001",
        "strength": "hard",
        "reason": "无关学科边。",
    },
]


def _zip_bytes(topics=None, dependencies=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data/topics.json", json.dumps(topics or TOPICS, ensure_ascii=False))
        archive.writestr(
            "data/dependencies.json",
            json.dumps(dependencies or DEPENDENCIES, ensure_ascii=False),
        )
    return buffer.getvalue()


async def _seed_subject(db_session) -> Subject:
    subject = Subject(name="数学", slug="math")
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)
    return subject


async def _seed_relation_type(db_session) -> KnowledgeRelationType:
    relation_type = KnowledgeRelationType(
        code="prerequisite", name="先修", category="prerequisite", sort_order=10
    )
    db_session.add(relation_type)
    await db_session.commit()
    await db_session.refresh(relation_type)
    return relation_type


def _bundle() -> CanonicalBundle:
    files = CnMathTaxonomyAdapter.read_zip(
        _zip_bytes(), ("topics.json", "dependencies.json")
    )
    return CnMathTaxonomyAdapter().parse(files, subjects={"math"})


def test_adapter_filters_non_target_subjects_and_maps_direction():
    bundle = _bundle()
    assert {n.external_id for n in bundle.nodes} == {"cnm_p001", "cnm_p002", "cnm_p003"}
    assert len(bundle.relations) == 2
    assert bundle.warnings
    first = bundle.relations[0]
    assert first.source_external_id == "cnm_p001"
    assert first.target_external_id == "cnm_p002"
    assert first.strength == "hard"
    node = next(n for n in bundle.nodes if n.external_id == "cnm_p002")
    assert node.domain == "数与代数"
    assert node.attributes["standards"]


async def test_import_preview_and_idempotent_apply(db_session):
    subject = await _seed_subject(db_session)
    await _seed_relation_type(db_session)
    bundle = _bundle()
    checksum = hashlib.sha256(_zip_bytes()).hexdigest()

    preview = await importer.preview(
        db_session, bundle=bundle, subject_id=subject.id, checksum=checksum
    )
    assert preview.to_create == 6  # 3 topics + 1 domain + 2 chapters
    assert preview.relations_to_create == 2
    assert preview.conflicts == 0

    result = await importer.apply(
        db_session, bundle=bundle, subject_id=subject.id, checksum=checksum,
        user_id=None,
    )
    assert result.created_nodes == 6
    assert result.created_relations == 2

    points = (await db_session.execute(select(KnowledgePoint))).scalars().all()
    assert len(points) == 6
    domain = next(p for p in points if p.node_type == "domain")
    chapter = next(p for p in points if p.node_type == "chapter")
    topic = next(p for p in points if p.name == "5以内数的大小")
    assert chapter.parent_id == domain.id
    assert topic.parent_id == chapter.id
    assert topic.description == "会比较 5 以内的数。"
    assert topic.attributes["semester"] == "上"

    relations = (await db_session.execute(select(KnowledgeRelation))).scalars().all()
    assert len(relations) == 2
    by_strength = {r.attributes["strength"]: r for r in relations}
    assert by_strength["hard"].source_id == next(
        p.id for p in points if p.name == "1到5各数的认识"
    )
    assert by_strength["hard"].target_id == topic.id
    assert all(r.status == "external" for r in relations)

    refs = (await db_session.execute(select(KnowledgeExternalRef))).scalars().all()
    assert len(refs) == 8  # 6 nodes + 2 relations

    second = await importer.apply(
        db_session, bundle=bundle, subject_id=subject.id, checksum=checksum,
        user_id=None,
    )
    assert second.created_nodes == 0
    assert second.linked_nodes == 6
    assert second.created_relations == 0
    assert second.skipped_relations == 2

    points_again = (await db_session.execute(select(KnowledgePoint))).scalars().all()
    assert len(points_again) == 6


async def test_import_can_update_existing_fields(db_session):
    subject = await _seed_subject(db_session)
    await _seed_relation_type(db_session)
    bundle = _bundle()
    checksum = hashlib.sha256(_zip_bytes()).hexdigest()
    await importer.apply(
        db_session, bundle=bundle, subject_id=subject.id, checksum=checksum
    )

    changed = _bundle()
    for node in changed.nodes:
        if node.external_id == "cnm_p001":
            node.description = "更新后的描述"
    result = await importer.apply(
        db_session, bundle=changed, subject_id=subject.id, checksum=checksum,
        update_existing=True,
    )
    assert result.updated_nodes == 3  # 3 topics; categories keep their fields

    fetched = (
        await db_session.execute(
            select(KnowledgePoint).where(KnowledgePoint.name == "1到5各数的认识")
        )
    ).scalars().one()
    assert fetched.description == "更新后的描述"


async def test_preview_detects_ambiguous_existing_nodes(db_session):
    subject = await _seed_subject(db_session)
    await _seed_relation_type(db_session)

    domain = KnowledgePoint(
        name="数与代数", slug="domain-number", subject_id=subject.id, node_type="domain"
    )
    db_session.add(domain)
    await db_session.commit()
    await db_session.refresh(domain)
    chapter = KnowledgePoint(
        name="一年级上册 第1单元 5以内数的认识", slug="chapter-1",
        subject_id=subject.id, parent_id=domain.id, node_type="chapter",
    )
    db_session.add(chapter)
    await db_session.commit()
    await db_session.refresh(chapter)
    db_session.add_all([
        KnowledgePoint(
            name="5以内数的大小", slug="dup-1", subject_id=subject.id,
            parent_id=chapter.id, node_type="procedural",
        ),
        KnowledgePoint(
            name="5以内数的大小", slug="dup-2", subject_id=subject.id,
            parent_id=chapter.id, node_type="procedural",
        ),
    ])
    await db_session.commit()

    bundle = _bundle()
    preview = await importer.preview(
        db_session, bundle=bundle, subject_id=subject.id, checksum="x"
    )
    assert preview.conflicts >= 1
    assert any("同名节点" in error for error in preview.errors)


async def _seed_admin(db_session) -> User:
    user = User(
        username="admin", full_name="admin", hashed_password="x",
        is_active=True, is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=user.id)}"}


async def test_external_import_api_preview_and_apply(client, db_session):
    subject = await _seed_subject(db_session)
    await _seed_relation_type(db_session)
    admin = await _seed_admin(db_session)
    payload = _zip_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    headers = _auth(admin)

    preview = await client.post(
        f"{API}/knowledge-points/import-external/preview",
        data={"subject_id": str(subject.id)},
        files={"file": ("bundle.zip", payload, "application/zip")},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["to_create"] == 6
    assert preview.json()["checksum"] == checksum

    bad = await client.post(
        f"{API}/knowledge-points/import-external",
        data={"subject_id": str(subject.id), "checksum": "wrong"},
        files={"file": ("bundle.zip", payload, "application/zip")},
        headers=headers,
    )
    assert bad.status_code == 400

    applied = await client.post(
        f"{API}/knowledge-points/import-external",
        data={"subject_id": str(subject.id), "checksum": checksum},
        files={"file": ("bundle.zip", payload, "application/zip")},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created_nodes"] == 6
    assert applied.json()["created_relations"] == 2
