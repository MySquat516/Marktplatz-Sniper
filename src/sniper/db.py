"""Datenbank: Tabellen, Engine und Migrationen (SQLite unter DATA_DIR/sniper.db).

Zeiten werden als UTC gespeichert und kommen zeitzonenbewusst zurück (SQLite kennt keine
Zeitzonen, deshalb der kleine Typ `UTCDateTime`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Zeiten müssen eine Zeitzone haben")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


search_targets = Table(
    "search_targets",
    Base.metadata,
    Column("search_id", ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True),
    Column("target_id", ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
)


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    platform: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text)
    spec_json: Mapped[str] = mapped_column(Text)
    interval_s: Mapped[int] = mapped_column(Integer, default=300)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    exclude_words: Mapped[str] = mapped_column(Text, default="")
    silence_days: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    notified_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_match_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    silence_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    targets: Mapped[list[Target]] = relationship(secondary=search_targets, lazy="selectin")


class Seen(Base):
    __tablename__ = "seen"
    __table_args__ = (UniqueConstraint("search_id", "platform", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    listing_json: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Target(Base):
    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    apprise_url: Mapped[str] = mapped_column(Text)
    status_notices: Mapped[bool] = mapped_column(Boolean, default=False)


class OutboxEntry(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"))
    search_id: Mapped[int | None] = mapped_column(
        ForeignKey("searches.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    attach_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def make_engine(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / 'sniper.db'}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def migrate(engine: Engine) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def get_setting(session: Session, key: str, default: str = "") -> str:
    value = session.scalar(select(Setting.value).where(Setting.key == key))
    return default if value is None else value


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
