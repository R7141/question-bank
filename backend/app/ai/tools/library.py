"""知识点与标签的只读 AI 工具。

不迁到 capability 层:纯读、无授权判定、无领域不变量,不满足纳入标准。
"""
from typing import Any, Dict
import logging

from sqlalchemy import select

from app.ai.contracts import ToolResult, ToolSpec
from app.ai.tools.registry import register
from app.capabilities.context import ExecutionContext
from app.core import permissions
from app.core.permissions import Permission
from app.crud.crud_knowledge_relation import knowledge_relation
from app.models.knowledge_point import KnowledgePoint
from app.models.tag import Tag
from app.models.tag_category import TagCategory
from app.services.knowledge_graph.retrieval import graph_context

logger = logging.getLogger(__name__)

SEARCH_KNOWLEDGE_POINTS_PARAMS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词或查询语句。"
        },
        "limit": {
            "type": "integer",
            "description": "返回结果的数量 (默认为 5)。",
            "default": 5
        }
    },
    "required": ["query"]
}

GET_AVAILABLE_TAGS_PARAMS = {
    "type": "object",
    "properties": {},
    "required": []
}

GET_KNOWLEDGE_POINT_RELATIONS_PARAMS = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "description": "知识点 ID（可从 search_knowledge_points 的结果中获取）。"
        },
        "direction": {
            "type": "string",
            "enum": ["in", "out", "both"],
            "description": "关系方向，默认 both。",
            "default": "both"
        },
        "relation_type_id": {
            "type": "integer",
            "description": "可选，按关系类型过滤。"
        },
        "limit": {
            "type": "integer",
            "description": "返回关系数量上限，默认 20。",
            "default": 20
        }
    },
    "required": ["id"]
}


async def search_knowledge_points(ctx: ExecutionContext, args: Dict[str, Any]) -> ToolResult:
    query = args.get("query")
    limit = args.get("limit", 5)

    if not query:
        return ToolResult.text("Please provide a query.")

    context = await graph_context.build(
        ctx.db, query=query, subject_id=ctx.subject_id, limit=limit
    )
    if not context:
        return ToolResult.text("No knowledge points found.")

    return ToolResult(content=context["text"])


async def get_knowledge_point_relations(
    ctx: ExecutionContext, args: Dict[str, Any]
) -> ToolResult:
    point_id = args.get("id")
    if not point_id:
        return ToolResult.text("Please provide a knowledge point id.")

    point = await ctx.db.get(KnowledgePoint, int(point_id))
    if not point:
        return ToolResult.text("Knowledge point not found.")
    if not permissions.can(
        ctx.actor, Permission.VIEW_QUESTION, subject_id=point.subject_id
    ):
        return ToolResult.text("No access to this knowledge point.")

    direction = args.get("direction", "both")
    if direction not in ("in", "out", "both"):
        direction = "both"
    relations = await knowledge_relation.get_for_point(
        ctx.db,
        point_id=point.id,
        direction=direction,
        relation_type_id=args.get("relation_type_id"),
        limit=int(args.get("limit", 20)),
    )
    if not relations:
        return ToolResult.text(f"知识点「{point.name}」暂无关系。")

    lines = [f"知识点：{point.name} [{point.id}]"]
    if point.description:
        lines.append(f"描述：{point.description}")
    for relation in relations:
        type_name = relation.relation_type.name if relation.relation_type else "关系"
        source_name = relation.source_point.name if relation.source_point else str(relation.source_id)
        target_name = relation.target_point.name if relation.target_point else str(relation.target_id)
        strength = (relation.attributes or {}).get("strength")
        meta = f"{strength}，" if strength else ""
        side = "出" if relation.source_id == point.id else "入"
        lines.append(
            f"- {type_name}（{side}）：{source_name} -> {target_name}"
            f"（{meta}{relation.status}）"
        )
    lines.append("以上关系来自知识图谱；external 状态表示外部导入、可能未经审核。")
    return ToolResult(content="\n".join(lines))


async def get_available_tags(ctx: ExecutionContext, args: Dict[str, Any]) -> ToolResult:
    res_cat = await ctx.db.execute(
        select(TagCategory).where(TagCategory.is_active == True).order_by(TagCategory.sort_order)  # noqa: E712
    )
    categories = res_cat.scalars().all()

    res_tag = await ctx.db.execute(select(Tag))
    tags = res_tag.scalars().all()

    tags_by_cat: Dict[Any, list] = {}
    for tag in tags:
        tags_by_cat.setdefault(tag.category_id, []).append(tag.name)

    tag_context_lines = []
    for cat in categories:
        cat_tags = tags_by_cat.get(cat.id, [])
        if cat_tags:
            tag_context_lines.append(f"- **{cat.name}**: {', '.join(cat_tags)}")

    if not tag_context_lines:
        return ToolResult.text("No tags available.")

    return ToolResult(content="\n".join(tag_context_lines))


register(ToolSpec(
    name="search_knowledge_points",
    description="在知识图谱中搜索相关知识点，返回 ID、层级、描述和一跳关系。当你需要为题目关联知识点，或需要了解概念之间的关系时，使用此工具；随后可用 get_knowledge_point_relations 深入查询。",
    parameters=SEARCH_KNOWLEDGE_POINTS_PARAMS,
    handler=search_knowledge_points,
))

register(ToolSpec(
    name="get_knowledge_point_relations",
    description="查询某个知识点的先修、后继、关联等知识图谱关系。需要判断知识点之间的依赖或扩展上下文时使用。",
    parameters=GET_KNOWLEDGE_POINT_RELATIONS_PARAMS,
    handler=get_knowledge_point_relations,
))

register(ToolSpec(
    name="get_available_tags",
    description="获取系统中所有可用的标签列表（按分类分组）。当你需要为题目打标签时，请先调用此工具查看有哪些标签可用，然后选择合适的标签名称。",
    parameters=GET_AVAILABLE_TAGS_PARAMS,
    handler=get_available_tags,
))
