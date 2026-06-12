from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


def utcnow():
    return datetime.now(timezone.utc)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id:       Mapped[str]           = mapped_column(String(200), primary_key=True)
    role:          Mapped[str]           = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str]           = mapped_column(Text, nullable=False)
    display_name:  Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    source_id:      Mapped[str]           = mapped_column(String(100), primary_key=True)
    display_name:   Mapped[str]           = mapped_column(String(200), nullable=False)
    system_type:    Mapped[str]           = mapped_column(String(50), nullable=False)
    base_url:       Mapped[str]           = mapped_column(Text, nullable=False)
    port:           Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    auth_type:      Mapped[str]           = mapped_column(String(50), nullable=False, default="bearer_token")
    auth_secret_ref:Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    project_key:    Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ticket_prefix:  Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    enabled:        Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineContext(Base):
    __tablename__ = "pipeline_context"

    case_id:      Mapped[str]           = mapped_column(String(100), primary_key=True)
    current_step: Mapped[str]           = mapped_column(String(100), default="start")
    context_json: Mapped[Optional[dict]]= mapped_column(JSONB, nullable=True)
    created_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id:         Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bug_id:          Mapped[str]           = mapped_column(String(100), nullable=False)
    source_id:       Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    engineer_id:     Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    step:            Mapped[str]           = mapped_column(String(100), nullable=False)
    status:          Mapped[str]           = mapped_column(String(50), default="done")
    summary:         Mapped[Optional[dict]]= mapped_column(JSONB, nullable=True)
    systems_queried: Mapped[Optional[list]]= mapped_column(JSONB, nullable=True)
    duration_ms:     Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemGroupRegistry(Base):
    __tablename__ = "system_group_registry"

    group_id:          Mapped[str]           = mapped_column(String(20), primary_key=True)
    status:            Mapped[str]           = mapped_column(String(50), default="active")
    priority:          Mapped[str]           = mapped_column(String(10), nullable=True)
    title:             Mapped[str]           = mapped_column(String(500), nullable=True)
    primary_source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at:        Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:        Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BugGroupMapping(Base):
    __tablename__ = "bug_group_mappings"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id:      Mapped[str]           = mapped_column(String(20), nullable=False)
    raw_ticket_id: Mapped[str]           = mapped_column(String(200), nullable=False)
    source_id:     Mapped[str]           = mapped_column(String(100), nullable=False)
    system_type:   Mapped[str]           = mapped_column(String(50), nullable=True)
    role:          Mapped[str]           = mapped_column(String(20), nullable=False, default="child")
    title:         Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    url:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status:        Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    severity:      Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    similarity_score:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    similarity_label:  Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    similarity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("raw_ticket_id", "source_id",
                         name="uq_bug_group_ticket"),
    )
