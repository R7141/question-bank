"""add smart PDF import fields to import_tasks

Revision ID: a9b8c7d6e5f4
Revises: e5f6a7b8c9d0
Create Date: 2026-10-23 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("import_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("method", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("subject_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stage", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("result_path", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("remote_task_id", sa.String(length=64), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_import_tasks_subject_id"), ["subject_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("import_tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_tasks_subject_id"))
        batch_op.drop_column("remote_task_id")
        batch_op.drop_column("result_path")
        batch_op.drop_column("stage")
        batch_op.drop_column("subject_id")
        batch_op.drop_column("method")
