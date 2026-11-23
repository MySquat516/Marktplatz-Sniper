"""Erste Tabellen

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "searches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("spec_json", sa.Text, nullable=False),
        sa.Column("interval_s", sa.Integer, nullable=False),
        sa.Column("max_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("exclude_words", sa.Text, nullable=False),
        sa.Column("silence_days", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("notified_state", sa.String(20), nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False),
        sa.Column("next_check_at", sa.DateTime, nullable=True),
        sa.Column("last_check_at", sa.DateTime, nullable=True),
        sa.Column("last_ok_at", sa.DateTime, nullable=True),
        sa.Column("last_match_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("silence_notified", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("apprise_url", sa.Text, nullable=False),
        sa.Column("status_notices", sa.Boolean, nullable=False),
    )
    op.create_table(
        "search_targets",
        sa.Column(
            "search_id",
            sa.Integer,
            sa.ForeignKey("searches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.Integer,
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "seen",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "search_id",
            sa.Integer,
            sa.ForeignKey("searches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("listing_json", sa.Text, nullable=False),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("search_id", "platform", "external_id"),
    )
    op.create_index("ix_seen_first_seen_at", "seen", ["first_seen_at"])
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "target_id", sa.Integer, sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "search_id",
            sa.Integer,
            sa.ForeignKey("searches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("attach_url", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("next_attempt_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("failed_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade() -> None:
    for table in ("settings", "outbox", "seen", "search_targets", "targets", "searches"):
        op.drop_table(table)
