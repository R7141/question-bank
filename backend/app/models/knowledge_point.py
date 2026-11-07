from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, UniqueConstraint, DateTime, JSON,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, backref
from .base import Base

# 分类节点（学科领域 / 教材章节）与真实知识点共用同一张表，靠 node_type 区分。
# 分类节点不参与题目关联、向量索引和 AI 打标，只用于组织树形结构。
CATEGORY_NODE_TYPES = ("domain", "chapter")


class KnowledgePoint(Base):
    """知识点表 (支持树形结构, 如: 数学 -> 高数 -> 微积分)"""
    __tablename__ = 'knowledge_points'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), index=True, nullable=False)
    slug = Column(String(255), index=True, nullable=False)
    
    subject_id = Column(Integer, ForeignKey('subjects.id'), nullable=False)
    parent_id = Column(Integer, ForeignKey('knowledge_points.id', ondelete='CASCADE'), nullable=True) # 父知识点ID

    # --- 通用知识图谱字段（全学科可空；学科专属信息放 attributes） ---
    description = Column(Text, nullable=True)
    node_type = Column(String(50), nullable=True, index=True)
    grade = Column(String(50), nullable=True)
    chapter = Column(String(255), nullable=True)
    learning_requirement = Column(Text, nullable=True)
    attributes = Column(JSON, nullable=True)
    source = Column(String(100), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    created_by = Column(Integer, ForeignKey('user.id'), nullable=True)
    updated_by = Column(Integer, ForeignKey('user.id'), nullable=True)
    
    creator = relationship("User", foreign_keys=[created_by], back_populates="knowledge_points_created")
    updater = relationship("User", foreign_keys=[updated_by], back_populates="knowledge_points_updated")

    # 关系
    subject = relationship("Subject", back_populates="knowledge_points")
    # 自关联: 获取子知识点
    children = relationship(
        "KnowledgePoint", 
        backref=backref('parent', remote_side=[id]),
        cascade="all, delete-orphan"
    )
    questions = relationship("Question", secondary="question_knowledge_points", back_populates="knowledge_points")

    __table_args__ = (
        UniqueConstraint('subject_id', 'slug', name='uq_knowledge_point_subject_slug'),
    )

    @property
    def is_category(self) -> bool:
        """分类节点（domain/chapter）不参与题目关联、向量索引和 AI 打标。"""
        return self.node_type in CATEGORY_NODE_TYPES
