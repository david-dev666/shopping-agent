"""Store complete trace JSON without a fixed character limit."""

import sqlalchemy as sa
from alembic import op

revision = "a4f91b2c730e"
down_revision = "7c8d9e0f1234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("trace") as batch:
        batch.alter_column(
            "steps_json", existing_type=sa.String(20000), type_=sa.Text(), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("trace") as batch:
        batch.alter_column(
            "steps_json", existing_type=sa.Text(), type_=sa.String(20000), existing_nullable=False
        )
