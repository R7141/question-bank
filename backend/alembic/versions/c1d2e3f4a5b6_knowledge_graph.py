"""add knowledge graph fields and relation tables

Revision ID: c1d2e3f4a5b6
Revises: a9b8c7d6e5f4
Create Date: 2026-11-07 00:00:00.000000

Additive migration:
  * knowledge_points: generic graph fields (description / node_type / grade /
    chapter / learning_requirement / attributes / source)
  * knowledge_relation_types: configurable semantic relation types
  * knowledge_relations: directed edges between knowledge points
  * knowledge_external_refs: external source/id tracking for idempotent imports

No existing knowledge point or question data is modified.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RELATION_TYPES = [
    {
        "code": "prerequisite",
        "name": "先修",
        "category": "prerequisite",
        "is_directed": True,
        "description": "学习目标知识点前需要掌握的知识点。",
        "sort_order": 10,
        "is_active": True,
    },
    {
        "code": "related",
        "name": "关联",
        "category": "association",
        "is_directed": False,
        "description": "存在知识联系，但没有固定学习顺序。",
        "sort_order": 20,
        "is_active": True,
    },
    {
        "code": "derived_from",
        "name": "推导",
        "category": "derivation",
        "is_directed": True,
        "description": "可由另一知识点推导得到。",
        "sort_order": 30,
        "is_active": True,
    },
    {
        "code": "applied_to",
        "name": "应用",
        "category": "application",
        "is_directed": True,
        "description": "可应用于另一知识点或具体问题。",
        "sort_order": 40,
        "is_active": True,
    },
    {
        "code": "uses",
        "name": "使用",
        "category": "application",
        "is_directed": True,
        "description": "跨学科使用另一知识点作为工具。",
        "sort_order": 50,
        "is_active": True,
    },
    {
        "code": "contrasts",
        "name": "对比",
        "category": "association",
        "is_directed": False,
        "description": "概念上形成对比。",
        "sort_order": 60,
        "is_active": True,
    },
    {
        "code": "causes",
        "name": "因果",
        "category": "association",
        "is_directed": True,
        "description": "存在因果关系。",
        "sort_order": 70,
        "is_active": True,
    },
    {
        "code": "precedes",
        "name": "时序",
        "category": "association",
        "is_directed": True,
        "description": "存在时间先后关系。",
        "sort_order": 80,
        "is_active": True,
    },
]


def upgrade() -> None:
    with op.batch_alter_table("knowledge_points", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("node_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("grade", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("chapter", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("learning_requirement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("attributes", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=100), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_knowledge_points_node_type"), ["node_type"], unique=False
        )

    op.create_table(
        "knowledge_relation_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("is_directed", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_relation_types")),
    )
    with op.batch_alter_table("knowledge_relation_types", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_relation_types_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_relation_types_code"), ["code"], unique=True
        )

    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("relation_type_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="verified", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source_id != target_id", name=op.f("ck_knowledge_relations_no_self_loop")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"],
            name=op.f("fk_knowledge_relations_created_by_user"),
        ),
        sa.ForeignKeyConstraint(
            ["relation_type_id"], ["knowledge_relation_types.id"],
            name=op.f("fk_knowledge_relations_relation_type_id_knowledge_relation_types"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge_points.id"],
            name=op.f("fk_knowledge_relations_source_id_knowledge_points"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"],
            name=op.f("fk_knowledge_relations_subject_id_subjects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["knowledge_points.id"],
            name=op.f("fk_knowledge_relations_target_id_knowledge_points"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["user.id"],
            name=op.f("fk_knowledge_relations_updated_by_user"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_relations")),
        sa.UniqueConstraint(
            "subject_id", "source_id", "target_id", "relation_type_id",
            name="uq_knowledge_relation_subject_source_target_type",
        ),
    )
    with op.batch_alter_table("knowledge_relations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_relations_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_relations_subject_id"), ["subject_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_relations_source_id"), ["source_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_relations_target_id"), ["target_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_relations_relation_type_id"),
            ["relation_type_id"], unique=False,
        )
        batch_op.create_index(
            "ix_knowledge_relations_source_type", ["source_id", "relation_type_id"], unique=False
        )
        batch_op.create_index(
            "ix_knowledge_relations_target_type", ["target_id", "relation_type_id"], unique=False
        )

    op.create_table(
        "knowledge_external_refs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_version", sa.String(length=100), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_external_refs")),
        sa.UniqueConstraint(
            "source", "entity_type", "external_id",
            name="uq_knowledge_external_ref_source_type_external",
        ),
    )
    with op.batch_alter_table("knowledge_external_refs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_external_refs_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_external_refs_entity_type"),
            ["entity_type"], unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_external_refs_entity_id"),
            ["entity_id"], unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_external_refs_source"), ["source"], unique=False
        )
        batch_op.create_index(
            "ix_knowledge_external_refs_entity", ["entity_type", "entity_id"], unique=False
        )

    relation_types = sa.table(
        "knowledge_relation_types",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("is_directed", sa.Boolean),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(relation_types, RELATION_TYPES)


def downgrade() -> None:
    op.drop_table("knowledge_external_refs")
    op.drop_table("knowledge_relations")
    op.drop_table("knowledge_relation_types")

    with op.batch_alter_table("knowledge_points", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_points_node_type"))
        batch_op.drop_column("source")
        batch_op.drop_column("attributes")
        batch_op.drop_column("learning_requirement")
        batch_op.drop_column("chapter")
        batch_op.drop_column("grade")
        batch_op.drop_column("node_type")
        batch_op.drop_column("description")
