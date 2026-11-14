"""Add explicit discipline tags to lectures."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_lecture_tags"
down_revision = "20261017_material_content"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "lectures",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade():
    op.drop_column("lectures", "tags")
