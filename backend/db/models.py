import sqlalchemy as sa
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Enum, Computed, Integer, JSON, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import uuid_utils

Base = declarative_base()


def generate_uuid():
    # UUIDv7: 48 bits Unix-ms timestamp + random bits. Time-ordered IDs
    # give B-tree indexes better insert locality than v4's pure random
    # (new rows append near the index's right edge instead of scattering
    # and fragmenting it). Behavior is unchanged for application code:
    # we still sort/query by `created_at` (not by id), and existing
    # v4 IDs keep working alongside new v7 ones — both are valid UUIDs.
    return str(uuid_utils.uuid7())


class WorkspaceTemplate(Base):
    __tablename__ = "workspace_templates"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSON, nullable=False, default=list, server_default="[]")
    color = Column(String, nullable=True)
    engine_config = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSONB, nullable=False, server_default="[]")
    engine_config = Column(
        JSONB,
        nullable=False,
        server_default='{"backend": "llama_cpp"}',
    )
    color = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.clock_timestamp())
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String, ForeignKey("workspace_templates.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_can_edit = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=0, index=True)

    sessions = relationship("Session", back_populates="workspace", cascade="all, delete-orphan")
    folders = relationship("Folder", back_populates="workspace", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    title = Column(String, default="New Diagnostic Session")
    is_pinned = Column(Boolean, default=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace = relationship("Workspace", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    session_id = Column(
        String,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(
        Enum("user", "assistant", "tool", "memory",
             name="messages_role_check",
             native_enum=False,
             create_constraint=False),  # alembic owns the constraint
        nullable=False,
    )
    content = Column(Text, nullable=False)
    # Lifecycle of the assistant generation that produced this row. Always
    # "complete" for user/memory rows. The /analyze finally block flips this
    # to "aborted" or "failed" when the stream did not reach a clean end.
    status = Column(String, nullable=False, default="complete", server_default="complete")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # JSON list of image-document references surfaced by this turn
    # ({id, filename, mime}). NULL for user/memory rows and for assistant
    # turns that referenced no files.
    referenced_docs = Column(JSONB, nullable=True)
    # JSON list of tool calls executed during this assistant turn
    # ([{name, args, result}, ...]). NULL on rows with no tool use;
    # history-rebuild treats a NULL value as "no tool calls".
    tool_calls = Column(JSONB, nullable=True)
    session = relationship("Session", back_populates="messages")


class Folder(Base):
    __tablename__ = "folders"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    name = Column(String)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace = relationship("Workspace", back_populates="folders")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    username = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    email = Column(String, nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    can_create_workspaces = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    must_change_password = Column(Boolean, nullable=False, default=False, server_default=text("false"))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    filename = Column(String, nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    is_global = Column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
    # Filesystem path to the original uploaded bytes. Populated for image
    # uploads; NULL for text uploads, which are reconstructable from chunks.
    # The file at this path is cleaned up by the after_delete listener at
    # the bottom of this module.
    storage_path = Column(String(512), nullable=True)
    # Async-ingestion state. 'processing' from the moment /upload commits
    # the row through the end of the background task; flips to 'ready'
    # when chunks + embeds are persisted, or 'error' if the pipeline fails.
    status = Column(String(16), nullable=False, server_default="ready")
    # Populated only when status='error'. Surfaces the upstream
    # exception message back to the frontend so the pill can show a
    # specific reason rather than a generic "processing failed".
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="documents")
    workspace = relationship("Workspace", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    workspace_id = Column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768))
    # tsvector for keyword search (hybrid RAG). Generated by PostgreSQL
    # from `content` using the `simple` config — no stemming, identifier-
    # friendly. Auto-populated on INSERT/UPDATE; SQLAlchemy never writes
    # to it directly. See migration 7a91b3e2d5c1 for the index + the
    # rationale for choosing `simple` over `english`.
    content_tsv = Column(
        TSVECTOR,
        Computed("to_tsvector('simple', content)", persisted=True),
    )
    document = relationship("Document", back_populates="chunks")


# ---------------------------------------------------------------------------
# Document.storage_path lifecycle: clean up the on-disk file when the row
# goes away. SQLAlchemy's `after_delete` event fires once the DELETE has
# been flushed; if the transaction later rolls back the file is gone, but
# the row is also still there — we treat that as acceptable since the
# inverse (orphan file) is the real risk.
# ---------------------------------------------------------------------------
import os as _os  # noqa: E402  — local import keeps the lifecycle hook self-contained
from sqlalchemy import event as _event  # noqa: E402


@_event.listens_for(Document, "after_delete")
def _delete_storage_file(_mapper, _connection, target):
    path = getattr(target, "storage_path", None)
    if not path:
        return
    try:
        _os.remove(path)
    except FileNotFoundError:
        pass
