from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException

from app import capabilities, models, schemas
from app.api import deps
from app.capabilities import knowledge_graph as knowledge_graph_caps
from app.core.permissions import Permission
from app.crud.crud_knowledge_relation import knowledge_relation, relation_type_crud

router = APIRouter()
type_router = APIRouter()


@router.get("/{id}", response_model=schemas.KnowledgeRelationDetail)
async def read_knowledge_relation(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    relation = await knowledge_relation.get_detail(db, id)
    if not relation:
        raise HTTPException(status_code=404, detail="知识关系不存在")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=relation.subject_id)
    return relation


@router.post("", response_model=schemas.KnowledgeRelation)
async def create_knowledge_relation(
    *,
    db: deps.SessionDep,
    relation_in: schemas.KnowledgeRelationCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await capabilities.run(
        "knowledge_relation.create",
        deps.api_context(db, current_user),
        relation_in,
    )


@router.put("/{id}", response_model=schemas.KnowledgeRelation)
async def update_knowledge_relation(
    *,
    db: deps.SessionDep,
    id: int,
    relation_in: schemas.KnowledgeRelationUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await capabilities.run(
        "knowledge_relation.update",
        deps.api_context(db, current_user),
        knowledge_graph_caps.KnowledgeRelationUpdateInput(id=id, data=relation_in),
    )


@router.delete("/{id}", response_model=schemas.KnowledgeRelation)
async def delete_knowledge_relation(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await capabilities.run(
        "knowledge_relation.delete",
        deps.api_context(db, current_user),
        knowledge_graph_caps.KnowledgeRelationIdInput(id=id),
    )


@type_router.get("", response_model=List[schemas.KnowledgeRelationType])
async def read_knowledge_relation_types(
    db: deps.SessionDep,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    return await relation_type_crud.list_all(db)


@type_router.post("", response_model=schemas.KnowledgeRelationType)
async def create_knowledge_relation_type(
    *,
    db: deps.SessionDep,
    type_in: schemas.KnowledgeRelationTypeCreate,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    try:
        return await relation_type_crud.create(
            db, obj_in=type_in, user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@type_router.put("/{id}", response_model=schemas.KnowledgeRelationType)
async def update_knowledge_relation_type(
    *,
    db: deps.SessionDep,
    id: int,
    type_in: schemas.KnowledgeRelationTypeUpdate,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    relation_type = await relation_type_crud.get(db, id)
    if not relation_type:
        raise HTTPException(status_code=404, detail="关系类型不存在")
    try:
        return await relation_type_crud.update(
            db, db_obj=relation_type, obj_in=type_in, user_id=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@type_router.delete("/{id}", response_model=schemas.KnowledgeRelationType)
async def delete_knowledge_relation_type(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_superuser),
) -> Any:
    relation_type = await relation_type_crud.get(db, id)
    if not relation_type:
        raise HTTPException(status_code=404, detail="关系类型不存在")
    return await relation_type_crud.remove(db, id=id, user_id=current_user.id)
