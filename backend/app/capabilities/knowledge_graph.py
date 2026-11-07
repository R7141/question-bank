"""知识图谱写路径能力。

读路径保持端点直连 CRUD；写关系需要统一鉴权与领域错误，故走 capability，
供 API / 未来的 AI 工具共用。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from app.core.permissions import Permission
from app.crud.crud_knowledge_relation import knowledge_relation
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_relation import KnowledgeRelation
from app.schemas.knowledge_graph import KnowledgeRelationCreate, KnowledgeRelationUpdate

from .base import Authz, Capability, Scope
from .context import ExecutionContext
from .errors import Invalid, NotFound, Unprocessable
from .registry import register


class KnowledgeRelationUpdateInput(BaseModel):
    id: int
    data: KnowledgeRelationUpdate


class KnowledgeRelationIdInput(BaseModel):
    id: int


def _translate_error(exc: ValueError) -> Exception:
    message = str(exc)
    if "不存在" in message:
        return NotFound(message)
    if "同一学科" in message or "学科不一致" in message:
        return Unprocessable(message)
    return Invalid(message)


@register
class CreateKnowledgeRelation(Capability[KnowledgeRelationCreate, KnowledgeRelation]):
    name = "knowledge_relation.create"
    description = "创建知识点之间的语义关系。"
    input_model = KnowledgeRelationCreate
    authz = Authz.PERMISSION
    permission = Permission.MANAGE_SUBJECT
    scope = Scope.SUBJECT
    mutating = True

    async def load(self, ctx: ExecutionContext, inp: KnowledgeRelationCreate) -> Any:
        source = await ctx.db.get(KnowledgePoint, inp.source_id)
        if not source:
            raise NotFound("源知识点不存在")
        return source

    async def execute(
        self, ctx: ExecutionContext, inp: KnowledgeRelationCreate, target: Any
    ) -> KnowledgeRelation:
        try:
            return await knowledge_relation.create(
                ctx.db, obj_in=inp, user_id=ctx.actor.id
            )
        except ValueError as exc:
            raise _translate_error(exc) from None


@register
class UpdateKnowledgeRelation(
    Capability[KnowledgeRelationUpdateInput, KnowledgeRelation]
):
    name = "knowledge_relation.update"
    description = "更新知识点关系的类型或说明。"
    input_model = KnowledgeRelationUpdateInput
    authz = Authz.PERMISSION
    permission = Permission.MANAGE_SUBJECT
    scope = Scope.SUBJECT
    mutating = True

    async def load(
        self, ctx: ExecutionContext, inp: KnowledgeRelationUpdateInput
    ) -> Optional[KnowledgeRelation]:
        relation = await knowledge_relation.get(ctx.db, inp.id)
        if not relation:
            raise NotFound("知识关系不存在")
        return relation

    async def execute(
        self,
        ctx: ExecutionContext,
        inp: KnowledgeRelationUpdateInput,
        target: Optional[KnowledgeRelation],
    ) -> KnowledgeRelation:
        assert target is not None
        try:
            return await knowledge_relation.update(
                ctx.db, db_obj=target, obj_in=inp.data, user_id=ctx.actor.id
            )
        except ValueError as exc:
            raise _translate_error(exc) from None


@register
class DeleteKnowledgeRelation(
    Capability[KnowledgeRelationIdInput, KnowledgeRelation]
):
    name = "knowledge_relation.delete"
    description = "删除一条知识关系。"
    input_model = KnowledgeRelationIdInput
    authz = Authz.PERMISSION
    permission = Permission.MANAGE_SUBJECT
    scope = Scope.SUBJECT
    mutating = True

    async def load(
        self, ctx: ExecutionContext, inp: KnowledgeRelationIdInput
    ) -> Optional[KnowledgeRelation]:
        relation = await knowledge_relation.get(ctx.db, inp.id)
        if not relation:
            raise NotFound("知识关系不存在")
        return relation

    async def execute(
        self, ctx: ExecutionContext, inp: KnowledgeRelationIdInput, target: Any
    ) -> KnowledgeRelation:
        assert target is not None
        return await knowledge_relation.remove(
            ctx.db, id=target.id, user_id=ctx.actor.id
        )
