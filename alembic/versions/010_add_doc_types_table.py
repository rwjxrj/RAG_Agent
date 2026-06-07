"""Add doc_types table for user-managed document types

Revision ID: 010
Revises: 009
Create Date: 2025-03-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_DOC_TYPES = [
    ("policy", "政策", "隐私政策、数据政策、通用政策等正式规则", 0),
    ("tos", "服务条款", "服务条款、使用条款、法律条款等内容", 1),
    ("faq", "常见问题", "常见问答、Q&A 格式的问题与答案", 2),
    ("howto", "操作指南", "教程、配置步骤、使用文档和排障指南", 3),
    ("pricing", "价格方案", "套餐、价格、产品方案、账单和购买信息", 4),
    ("other", "其他", "博客、关于我们、新闻和其他通用内容", 5),
]


def upgrade() -> None:
    op.create_table(
        "doc_types",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_doc_types_key", "doc_types", ["key"], unique=True)

    for key, label, description, sort_order in DEFAULT_DOC_TYPES:
        op.execute(
            sa.text(
                "INSERT INTO doc_types (id, key, label, description, sort_order) "
                "SELECT gen_random_uuid(), :k, :lbl, :desc, :ord "
                "WHERE NOT EXISTS (SELECT 1 FROM doc_types WHERE key = :k)"
            ).bindparams(k=key, lbl=label, desc=description, ord=sort_order)
        )


def downgrade() -> None:
    op.drop_index("ix_doc_types_key", table_name="doc_types")
    op.drop_table("doc_types")
