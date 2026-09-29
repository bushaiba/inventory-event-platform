from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "event_records"
    __table_args__ = (
        UniqueConstraint("stream_id", "stream_version", name="uq_stream_version"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stream_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    command_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ContainerProjection(Base):
    __tablename__ = "container_projection"

    container_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    last_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class CommandAudit(Base):
    __tablename__ = "command_audit"

    command_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    command_type: Mapped[str] = mapped_column(String(40), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    before_version: Mapped[int | None] = mapped_column(Integer)
    after_version: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_records.event_id"), unique=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class DeadLetterMessage(Base):
    __tablename__ = "dead_letter_messages"

    dead_letter_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbox_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)


class ScheduledRestore(Base):
    __tablename__ = "scheduled_restores"

    restore_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_command_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    restore_location: Mapped[str] = mapped_column(String(80), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    completed_command_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)


def build_engine(database_url: str):
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


def build_session_factory(database_url: str):
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
