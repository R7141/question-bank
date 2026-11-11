from app.ai.tools.library import get_knowledge_point_relations, search_knowledge_points
from app.capabilities.context import ExecutionContext, Surface
from app.core.vector_store import VectorStore
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation, KnowledgeRelationType
from app.models.subject import Subject
from app.models.user import User
from app.services.knowledge_graph.retrieval import graph_context


async def _seed(db_session):
    subject = Subject(name="数学", slug="math")
    db_session.add(subject)
    await db_session.commit()
    await db_session.refresh(subject)

    a = KnowledgePoint(
        name="一元一次方程", slug="linear-equation", subject_id=subject.id,
        node_type="procedural", description="会解一元一次方程。", chapter="七年级上册",
    )
    b = KnowledgePoint(
        name="一元二次方程", slug="quadratic-equation", subject_id=subject.id,
        node_type="procedural", description="会解一元二次方程。", chapter="九年级上册",
    )
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)

    relation_type = KnowledgeRelationType(
        code="prerequisite", name="先修", category="prerequisite", sort_order=10
    )
    db_session.add(relation_type)
    await db_session.commit()
    await db_session.refresh(relation_type)
    db_session.add(
        KnowledgeRelation(
            subject_id=subject.id,
            source_id=a.id,
            target_id=b.id,
            relation_type_id=relation_type.id,
            description="学一元二次方程前先掌握一元一次方程。",
            source="cn-math-taxonomy",
            status="external",
            attributes={"strength": "hard", "ai_reviewed": False},
        )
    )
    await db_session.commit()

    user = User(
        username="admin", full_name="admin", hashed_password="x",
        is_active=True, is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return subject, a, b, user


def _enable_vector(monkeypatch):
    monkeypatch.setattr(VectorStore, "is_available", classmethod(lambda cls: True))


async def test_context_for_ids_includes_description_and_relations(db_session, monkeypatch):
    _enable_vector(monkeypatch)
    subject, a, b, _ = await _seed(db_session)

    text = await graph_context.context_for_ids(
        db_session, ids=[a.id, b.id], subject_id=subject.id
    )

    assert text is not None
    assert "一元一次方程" in text
    assert "会解一元二次方程" in text
    assert "先修" in text
    assert "hard" in text
    assert "external" in text


async def test_context_build_uses_vector_results(db_session, monkeypatch):
    _enable_vector(monkeypatch)
    subject, a, b, _ = await _seed(db_session)

    def fake_search(query, subject_id=None, limit=10):
        return {
            "ids": [[str(a.id), str(b.id)]],
            "documents": [["数学 > 方程 > 一元一次方程", "数学 > 方程 > 一元二次方程"]],
            "distances": [[0.1, 0.2]],
        }

    monkeypatch.setattr(
        VectorStore, "search_similar", classmethod(lambda cls, **kwargs: fake_search(**kwargs))
    )
    result = await graph_context.build(
        db_session, query="解方程", subject_id=subject.id, limit=5
    )

    assert result is not None
    assert result["ids"] == [a.id, b.id]
    assert "数学 > 方程 > 一元一次方程" in result["text"]


async def test_context_degrades_when_embedding_unavailable(db_session, monkeypatch):
    monkeypatch.setattr(VectorStore, "is_available", classmethod(lambda cls: False))
    subject, a, _, _ = await _seed(db_session)

    assert await graph_context.context_for_ids(
        db_session, ids=[a.id], subject_id=subject.id
    ) is None
    assert await graph_context.build(
        db_session, query="x", subject_id=subject.id
    ) is None


async def test_search_tool_returns_ids_and_relations(db_session, monkeypatch):
    _enable_vector(monkeypatch)
    subject, a, b, user = await _seed(db_session)

    monkeypatch.setattr(
        VectorStore,
        "search_similar",
        classmethod(
            lambda cls, **kwargs: {
                "ids": [[str(b.id)]],
                "documents": [["数学 > 方程 > 一元二次方程"]],
                "distances": [[0.1]],
            }
        ),
    )
    ctx = ExecutionContext(
        db=db_session, actor=user, surface=Surface.CHAT, subject_id=subject.id
    )
    result = await search_knowledge_points(ctx, {"query": "二次方程", "limit": 5})

    assert f"[{b.id}]" in result.content
    assert "先修" in result.content


async def test_relation_tool_formats_direction_and_strength(db_session):
    subject, a, b, user = await _seed(db_session)
    ctx = ExecutionContext(
        db=db_session, actor=user, surface=Surface.CHAT, subject_id=subject.id
    )

    result = await get_knowledge_point_relations(ctx, {"id": b.id, "direction": "in"})

    assert "一元二次方程" in result.content
    assert "先修" in result.content
    assert "入" in result.content
    assert "hard" in result.content
    assert "external" in result.content


async def test_enrich_passes_graph_context_to_rerank(db_session, monkeypatch):
    _enable_vector(monkeypatch)
    subject, a, b, _ = await _seed(db_session)
    from app.services.importing.enrich import KnowledgePointEnricher
    from app.services.kp_retriever import KnowledgePointRetriever

    class FakeQuestion:
        content = "解一元二次方程"
        knowledge_points = []
        knowledge_point_ids = []

    class FakeProvider:
        def __init__(self):
            self.items = None

        async def batch_rerank_knowledge_points(self, items, config=None):
            self.items = items
            return {items[0]["id"]: [items[0]["candidates"][0]]}

    async def fake_retrieve(**kwargs):
        return {
            "ids": [[str(a.id), str(b.id)]],
            "documents": [["数学 > 方程 > 一元一次方程", "数学 > 方程 > 一元二次方程"]],
            "distances": [[0.1, 0.2]],
        }

    monkeypatch.setattr(
        KnowledgePointRetriever, "retrieve", staticmethod(fake_retrieve)
    )
    provider = FakeProvider()
    question = FakeQuestion()
    await KnowledgePointEnricher().enrich(
        [question], subject_id=subject.id, provider=provider, config={}, db=db_session
    )

    assert provider.items is not None
    assert "先修" in provider.items[0]["context"]
    assert question.knowledge_point_ids
