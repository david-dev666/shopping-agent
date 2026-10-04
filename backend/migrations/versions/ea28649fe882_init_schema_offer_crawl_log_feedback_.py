"""init schema: offer/crawl_log/feedback/trace

Revision ID: ea28649fe882
Revises:
Create Date: 2026-10-03 13:49:24.295004

直接复用 ORM 元数据建表（`app.storage.db:Base`），
迁移与应用模型永远一致，避免手写 DDL 与模型漂移。
"""

from collections.abc import Sequence

from alembic import op

from app.storage.db import Base

# revision identifiers, used by Alembic.
revision: str = "ea28649fe882"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """按 ORM 元数据建表（已存在的表会跳过）。"""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """删除全部表。"""
    Base.metadata.drop_all(bind=op.get_bind())
