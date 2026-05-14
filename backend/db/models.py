import sqlalchemy as sa
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
import uuid

Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    slug = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    enabled_tools = Column(JSONB, nullable=False, server_default="[]")
    engine_config = Column(
        JSONB,
        nullable=False,
        server_default='{"backend": "llama_cpp"}',
    )
    is_builtin = Column(Boolean, nullable=False, default=False, server_default="false")
    color = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.clock_timestamp())

    sessions = relationship("Session", back_populates="workspace", cascade="all, delete-orphan")
    folders = relationship("Folder", back_populates="workspace", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="workspace", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    title = Column(String, default="New Diagnostic Session")
    is_pinned = Column(Boolean, default=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
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
    session = relationship("Session", back_populates="messages")


class Folder(Base):
    __tablename__ = "folders"
    id = Column(String, primary_key=True)
    name = Column(String)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace = relationship("Workspace", back_populates="folders")


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    filename = Column(String, nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    is_global = Column(Boolean, default=False, server_default=sa.text("false"), nullable=False)
    # Filesystem path to the original uploaded bytes. Populated for image
    # uploads (Milestone 2 of the VLM spec); NULL for text uploads, which
    # are reconstructable from chunks. The file at this path is cleaned up
    # by the after_delete listener at the bottom of this module.
    storage_path = Column(String(512), nullable=True)
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
