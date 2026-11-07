"""Knowledge graph import contracts.

External taxonomies are converted into these provider-neutral structures before
touching QB's own models. This keeps the importer independent from any single
source format.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CanonicalKnowledgeNode(BaseModel):
    external_id: str
    name: str
    subject: str
    domain: Optional[str] = None
    chapter: Optional[str] = None
    grade: Optional[str] = None
    semester: Optional[str] = None
    node_type: Optional[str] = None
    description: Optional[str] = None
    learning_requirement: Optional[str] = None
    mastery_criteria: List[str] = Field(default_factory=list)
    diagnostic_question: Optional[Dict[str, Any]] = None
    standards: List[Dict[str, Any]] = Field(default_factory=list)
    root_reason: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)


class CanonicalKnowledgeRelation(BaseModel):
    external_id: str
    source_external_id: str  # prerequisite
    target_external_id: str  # dependent
    relation_type_code: str = "prerequisite"
    description: Optional[str] = None
    strength: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)


class CanonicalBundle(BaseModel):
    source: str
    version: Optional[str] = None
    subject_filter: List[str] = Field(default_factory=list)
    nodes: List[CanonicalKnowledgeNode] = Field(default_factory=list)
    relations: List[CanonicalKnowledgeRelation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ImportAction(BaseModel):
    external_id: str
    name: str
    node_type: str
    action: str  # create / link / update / skip / conflict
    reason: Optional[str] = None


class ImportPreview(BaseModel):
    source: str
    subject_id: int
    checksum: str
    total_nodes: int
    total_relations: int
    to_create: int = 0
    to_link: int = 0
    to_update: int = 0
    skipped: int = 0
    conflicts: int = 0
    relations_to_create: int = 0
    relations_skipped: int = 0
    actions: List[ImportAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    source: str
    subject_id: int
    created_nodes: int = 0
    linked_nodes: int = 0
    updated_nodes: int = 0
    created_relations: int = 0
    skipped_relations: int = 0
    vector_synced: bool = False
    duration: float = 0.0
    errors: List[str] = Field(default_factory=list)
