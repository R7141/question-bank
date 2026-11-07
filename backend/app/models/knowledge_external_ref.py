from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base


class KnowledgeExternalRef(Base):
    """外部知识体系来源映射，用于追踪原始 ID 与保证重复导入幂等。"""

    __tablename__ = "knowledge_external_refs"

    id = Column(Integer, primary_key=True, index=True)
    # knowledge_point / knowledge_relation
    entity_type = Column(String(30), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    external_version = Column(String(100), nullable=True)
    payload_hash = Column(String(64), nullable=True)
    raw = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source", "entity_type", "external_id",
            name="uq_knowledge_external_ref_source_type_external",
        ),
        Index("ix_knowledge_external_refs_entity", "entity_type", "entity_id"),
    )
