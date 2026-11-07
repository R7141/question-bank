from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.services.knowledge_graph.contracts import (
    ImportAction,
    ImportPreview,
    ImportResult,
)

from .knowledge_point import KnowledgePoint


class KnowledgeRelationTypeBase(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    is_directed: bool = True
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class KnowledgeRelationTypeCreate(KnowledgeRelationTypeBase):
    pass


class KnowledgeRelationTypeUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    is_directed: Optional[bool] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class KnowledgeRelationType(KnowledgeRelationTypeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeRelationBase(BaseModel):
    source_id: int
    target_id: int
    relation_type_id: int
    description: Optional[str] = None
    weight: Optional[float] = None
    source: Optional[str] = None
    status: str = "verified"
    confidence: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None


class KnowledgeRelationCreate(KnowledgeRelationBase):
    # 省略时由 source 知识点推导，避免前端重复传。
    subject_id: Optional[int] = None


class KnowledgeRelationUpdate(BaseModel):
    relation_type_id: Optional[int] = None
    description: Optional[str] = None
    weight: Optional[float] = None
    source: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[float] = None
    attributes: Optional[Dict[str, Any]] = None


class KnowledgeRelation(KnowledgeRelationBase):
    id: int
    subject_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeRelationDetail(KnowledgeRelation):
    relation_type: Optional[KnowledgeRelationType] = None
    source_point: Optional[KnowledgePoint] = None
    target_point: Optional[KnowledgePoint] = None


class KnowledgeExternalRefBase(BaseModel):
    entity_type: str
    entity_id: int
    source: str
    external_id: str
    external_version: Optional[str] = None
    payload_hash: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class KnowledgeExternalRefCreate(KnowledgeExternalRefBase):
    pass


class KnowledgeExternalRef(KnowledgeExternalRefBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
