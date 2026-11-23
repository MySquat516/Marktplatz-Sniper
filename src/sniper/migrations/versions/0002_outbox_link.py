"""Link einer Meldung getrennt speichern

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outbox") as batch:
        batch.add_column(sa.Column("link_url", sa.Text, nullable=True))
        batch.add_column(sa.Column("link_label", sa.String(100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outbox") as batch:
        batch.drop_column("link_label")
        batch.drop_column("link_url")
