"""Add immutable candidate snapshots for server-side refinement."""

from alembic import op

from app.storage.db import CandidateSnapshotORM

revision = "7c8d9e0f1234"
down_revision = "ea28649fe882"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration also uses current metadata; support both fresh and existing DBs.
    CandidateSnapshotORM.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    CandidateSnapshotORM.__table__.drop(bind=op.get_bind(), checkfirst=True)
