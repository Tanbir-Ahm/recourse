"""
api/db/models.py -- the API's database tables (WEBSITE_DESIGN.md section 4; step A2). PostgreSQL in production; SQLAlchemy 2 declarative.
Rules that shaped it (owner's decisions of 2026-10-20, D3 and D4, and the design's privacy section):
  * Everything a person owns (identities, sessions, consents, chats, messages, notes, feedback) is deleted WITH the person (ON DELETE CASCADE): "delete my data" is one delete of the users row.
  * Rows that must outlive a deletion for billing, abuse and audit (usage_events, audit_log, deletion_requests) keep no message text and are DE-IDENTIFIED instead (user_id set to NULL).
  * Fixed lists (roles, kinds, statuses) are text columns with CHECK constraints, not Postgres enums: a new value is a one-line migration.
  * Plans and quotas are rows (plans, entitlements), never code: the price and the limits are not decided yet (D7). Subscriptions, payments and webhook events are NOT here: they belong to Phase C.
  * Anonymous trial (D4: three layman questions without signing in): the question text IS stored, under a random device id and no IP address, for 90 days (anon_questions.expires_at); the per-device and per-IP daily
    counters (anon_counters) keep only a scrambled IP and a count.
Nothing here is used by the answer route yet: the ask route still needs no database.
"""
import datetime
import uuid

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")

ROLES = ("user", "lawyer", "reviewer", "admin")
USER_STATUSES = ("active", "suspended", "deleted")
AUDIENCES = ("layman", "lawyer")
DOCUMENTS = ("privacy", "terms", "data_use")
MESSAGE_ROLES = ("user", "assistant")
FEEDBACK_KINDS = ("wrong_law", "wrong_case", "wrong_quote", "missing", "unclear", "helpful", "other")
FEEDBACK_STATUSES = ("new", "reviewed", "closed")
USAGE_KINDS = ("answer_layman", "answer_lawyer", "draft", "doc_read", "anon_answer")
PERIODS = ("day", "month", "none")
COUNTER_KINDS = ("device", "ip")


def _in(column, values):
    return f"{column} IN (" + ", ".join("'" + v + "'" for v in values) + ")"


class Base(DeclarativeBase):
    pass


def _id():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime.datetime] = _created()
    entitlements: Mapped[list["Entitlement"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Entitlement(Base):
    """One limit of one plan: feature, period, how many (NULL = unlimited). A change is a NEW version row; the highest version is the one in force."""
    __tablename__ = "entitlements"
    __table_args__ = (UniqueConstraint("plan_id", "feature", "version", name="uq_entitlement_version"), CheckConstraint(_in("period", PERIODS), name="ck_entitlement_period"),
                      CheckConstraint("limit_count IS NULL OR limit_count >= 0", name="ck_entitlement_limit"))
    id: Mapped[uuid.UUID] = _id()
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    feature: Mapped[str] = mapped_column(String(60), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    limit_count: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    effective_from: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    plan: Mapped[Plan] = relationship(back_populates="entitlements")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="ck_user_email_lower"), CheckConstraint(_in("role", ROLES), name="ck_user_role"),
                      CheckConstraint(_in("status", USER_STATUSES), name="ck_user_status"))
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    display_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    language: Mapped[str | None] = mapped_column(String(10))
    age_confirmed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = _created()


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = _created()


class Session(Base):
    """The browser path's login (the Next.js front end). id is the HASH of the cookie value, never the value itself."""
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = _created()


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (CheckConstraint(_in("document", DOCUMENTS), name="ck_consent_document"), Index("ix_consents_user_document", "user_id", "document"))
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (CheckConstraint(_in("audience", AUDIENCES), name="ck_chat_audience"), Index("ix_chats_user_updated", "user_id", "updated_at"))
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    audience: Mapped[str] = mapped_column(String(10), nullable=False, server_default="layman")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = _created()
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    messages: Mapped[list["Message"]] = relationship(back_populates="chat", cascade="all, delete-orphan", order_by="Message.seq")


class Message(Base):
    """One turn. For an assistant turn `result` holds the engine's whole structured result (sources, notices, boxes, authorities...) so a refresh shows exactly what was shown."""
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("chat_id", "seq", name="uq_message_chat_seq"), CheckConstraint(_in("role", MESSAGE_ROLES), name="ck_message_role"))
    id: Mapped[uuid.UUID] = _id()
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONType)
    engine_commit: Mapped[str | None] = mapped_column(String(40))
    style: Mapped[str | None] = mapped_column(String(20))
    state: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[str | None] = mapped_column(String(40))
    cost_inr: Mapped[float | None] = mapped_column(Numeric(8, 2))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = _created()
    chat: Mapped[Chat] = relationship(back_populates="messages")


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = _created()
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint(_in("kind", FEEDBACK_KINDS), name="ck_feedback_kind"), CheckConstraint(_in("status", FEEDBACK_STATUSES), name="ck_feedback_status"))
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="new")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime.datetime] = _created()


class UsageEvent(Base):
    """What was used and what it cost. No message text. user_id becomes NULL when the person is deleted: the row stays for billing and abuse."""
    __tablename__ = "usage_events"
    __table_args__ = (CheckConstraint(_in("kind", USAGE_KINDS), name="ck_usage_kind"), Index("ix_usage_user_at", "user_id", "at"))
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    cost_inr: Mapped[float | None] = mapped_column(Numeric(8, 2))
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    plan_id_at_time: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AuditLog(Base):
    """Who did what to what. `detail` never holds message text."""
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = _id()
    at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict | None] = mapped_column(JSONType)


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AnonQuestion(Base):
    """A question asked without signing in (D4). Stored under a random device id, with NO ip address, and deleted after expires_at (90 days). Readable only by the owner and the reviewer."""
    __tablename__ = "anon_questions"
    __table_args__ = (CheckConstraint(_in("audience", AUDIENCES), name="ck_anon_audience"), Index("ix_anon_questions_expires", "expires_at"), Index("ix_anon_questions_device", "device_id"))
    id: Mapped[uuid.UUID] = _id()
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(10), nullable=False, server_default="layman")
    result_state: Mapped[str | None] = mapped_column(String(40))
    cost_inr: Mapped[float | None] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime.datetime] = _created()
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnonCounter(Base):
    """Per-day counts for the anonymous trial's caps: by device (a random id in a cookie) and by a scrambled IP. No question text, no raw IP."""
    __tablename__ = "anon_counters"
    __table_args__ = (CheckConstraint(_in("kind", COUNTER_KINDS), name="ck_anon_counter_kind"), CheckConstraint("count >= 0", name="ck_anon_counter_count"))
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
