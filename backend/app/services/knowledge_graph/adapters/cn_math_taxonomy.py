from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from app.services.knowledge_graph.contracts import (
    CanonicalBundle,
    CanonicalKnowledgeNode,
    CanonicalKnowledgeRelation,
)

from .base import KnowledgeSourceAdapter

SOURCE_NAME = "cn-math-taxonomy"
ALLOWED_FILES = (
    "topics.json",
    "dependencies.json",
    "id-aliases.json",
    "cn-curriculum-standards.json",
)


class CnMathTaxonomyAdapter(KnowledgeSourceAdapter):
    source_name = SOURCE_NAME

    def parse(
        self,
        files: Dict[str, bytes],
        *,
        subjects: Optional[Set[str]] = None,
    ) -> CanonicalBundle:
        if "topics.json" not in files:
            raise ValueError("压缩包缺少 topics.json")
        if "dependencies.json" not in files:
            raise ValueError("压缩包缺少 dependencies.json")

        subject_filter: Set[str] = subjects or {"math"}
        raw_topics = json.loads(files["topics.json"].decode("utf-8"))
        raw_relations = json.loads(files["dependencies.json"].decode("utf-8"))
        if not isinstance(raw_topics, list):
            raise ValueError("topics.json 顶层必须是数组")
        if not isinstance(raw_relations, list):
            raise ValueError("dependencies.json 顶层必须是数组")

        warnings: List[str] = []
        nodes: List[CanonicalKnowledgeNode] = []
        seen_ids: Set[str] = set()
        skipped_subjects: Dict[str, int] = {}

        for raw in raw_topics:
            if not isinstance(raw, dict):
                warnings.append("topics.json 中存在非对象记录，已跳过")
                continue
            external_id = str(raw.get("id") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not external_id or not name:
                warnings.append("存在缺少 id/name 的知识点，已跳过")
                continue
            if external_id in seen_ids:
                raise ValueError(f"topics.json 存在重复 id: {external_id}")

            subject = str(raw.get("subject") or "math").strip().lower()
            if subject not in subject_filter:
                skipped_subjects[subject] = skipped_subjects.get(subject, 0) + 1
                continue

            seen_ids.add(external_id)
            attributes: Dict[str, Any] = {
                "semester": raw.get("semester"),
                "mastery_criteria": raw.get("mastery_criteria") or [],
                "diagnostic_question": raw.get("diagnostic_question"),
                "standards": raw.get("standards") or [],
                "root_reason": raw.get("root_reason"),
                "external": raw.get("external"),
                "cn_subject": subject,
            }
            if raw.get("mathLinks"):
                attributes["mathLinks"] = raw["mathLinks"]

            nodes.append(
                CanonicalKnowledgeNode(
                    external_id=external_id,
                    name=name,
                    subject=subject,
                    domain=raw.get("domain"),
                    chapter=raw.get("chapter"),
                    grade=str(raw["grade"]) if raw.get("grade") is not None else None,
                    semester=raw.get("semester"),
                    node_type=raw.get("type"),
                    description=raw.get("description"),
                    mastery_criteria=raw.get("mastery_criteria") or [],
                    diagnostic_question=raw.get("diagnostic_question"),
                    standards=raw.get("standards") or [],
                    root_reason=raw.get("root_reason"),
                    attributes=attributes,
                    raw=raw,
                )
            )

        for subject, count in skipped_subjects.items():
            warnings.append(f"已跳过非目标学科 {subject} 的 {count} 个节点")

        relations: List[CanonicalKnowledgeRelation] = []
        relation_ids: Set[str] = set()
        for raw in raw_relations:
            if not isinstance(raw, dict):
                warnings.append("dependencies.json 中存在非对象记录，已跳过")
                continue
            target_id = str(raw.get("topicId") or "").strip()
            source_id = str(raw.get("prerequisiteId") or "").strip()
            if target_id not in seen_ids or source_id not in seen_ids:
                # 非目标学科或缺失端点；静默跳过非目标学科，缺失端点记警告。
                continue
            external_id = f"{source_id}->{target_id}"
            if external_id in relation_ids:
                warnings.append(f"重复先修边已跳过: {external_id}")
                continue
            relation_ids.add(external_id)
            strength = raw.get("strength")
            relations.append(
                CanonicalKnowledgeRelation(
                    external_id=external_id,
                    source_external_id=source_id,
                    target_external_id=target_id,
                    relation_type_code="prerequisite",
                    description=raw.get("reason"),
                    strength=strength,
                    attributes={
                        "strength": strength,
                        "ai_reviewed": False,
                    },
                    raw=raw,
                )
            )

        return CanonicalBundle(
            source=SOURCE_NAME,
            subject_filter=sorted(subject_filter),
            nodes=nodes,
            relations=relations,
            warnings=warnings,
        )
