from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from .base import Base


class KnowledgeRelationType(Base):
    """可配置的知识关系类型（先修 / 关联 / 推导 / 应用 ...）。"""

    __tablename__ = "knowledge_relation_types"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=True)
    is_directed = Column(Boolean, nullable=False, default=True, server_default="1")
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class KnowledgeRelation(Base):
    """知识点之间的语义关系。

    方向约定：source 是关系起点，target 是终点。对 prerequisite 而言，
    source 是先修知识点，target 是后继知识点。
    """

    __tablename__ = "knowledge_relations"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(
        Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id = Column(
        Integer, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id = Column(
        Integer, ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type_id = Column(
        Integer, ForeignKey("knowledge_relation_types.id"), nullable=False, index=True
    )

    description = Column(Text, nullable=True)
    weight = Column(Float, nullable=True)
    source = Column(String(100), nullable=True)
    # verified = 人工确认；external = 外部导入；ai_inferred = AI 推断
    status = Column(String(20), nullable=False, default="verified", server_default="verified")
    confidence = Column(Float, nullable=True)
    attributes = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id"), nullable=True)

    relation_type = relationship("KnowledgeRelationType")
    source_point = relationship("KnowledgePoint", foreign_keys=[source_id])
    target_point = relationship("KnowledgePoint", foreign_keys=[target_id])

    __table_args__ = (
        UniqueConstraint(
            "subject_id", "source_id", "target_id", "relation_type_id",
            name="uq_knowledge_relation_subject_source_target_type",
        ),
        CheckConstraint("source_id != target_id", name="no_self_loop"),
        Index("ix_knowledge_relations_source_type", "source_id", "relation_type_id"),
        Index("ix_knowledge_relations_target_type", "target_id", "relation_type_id"),
    )
