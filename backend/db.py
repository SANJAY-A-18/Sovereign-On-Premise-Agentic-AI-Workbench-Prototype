"""
Database module for the Sovereign On-Premise Agentic AI Workbench.
Uses SQLAlchemy with SQLite for offline data persistence.
Provides models for Users, Agents, Runs, Steps, Approvals, Audit Logs, and Documents.
Also sets up a demo SQLite database (data/demo.db) with a sample 'students' table.
"""

from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Generator
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from backend.config import settings

from sqlalchemy import event

# Main Sovereign DB Engine
# SQLite connect args needed for multi-threaded FastAPI access and busy timeouts
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0},
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
    except Exception:
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """User account model with role-based access control (admin or user)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # 'admin' or 'user'
    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship("Run", back_populates="user")
    documents = relationship("Document", back_populates="uploader")


class Agent(Base):
    """Configurable AI Agent specification."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    system_prompt = Column(Text, nullable=False)
    model = Column(String(100), nullable=False, default=settings.OLLAMA_MODEL)
    allowed_tools = Column(Text, nullable=False, default="[]")  # JSON string array
    temperature = Column(Float, default=0.2)
    created_at = Column(DateTime, default=datetime.utcnow)

    runs = relationship("Run", back_populates="agent")

    def get_allowed_tools_list(self) -> list:
        try:
            return json.loads(self.allowed_tools)
        except Exception:
            return []

    def set_allowed_tools_list(self, tools: list):
        self.allowed_tools = json.dumps(tools)


class Run(Base):
    """Execution trace of an agent invocation for a user query."""
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    question = Column(Text, nullable=False)
    final_answer = Column(Text, nullable=True)
    status = Column(String(50), default="running")  # running, paused_for_approval, completed, failed, denied
    total_latency_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="runs")
    agent = relationship("Agent", back_populates="runs")
    steps = relationship("Step", back_populates="run", cascade="all, delete-orphan", order_by="Step.step_number")
    approvals = relationship("Approval", back_populates="run", cascade="all, delete-orphan")


class Step(Base):
    """Detailed step within an agent run (LLM call, tool call, retry, policy decision)."""
    __tablename__ = "steps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    step_type = Column(String(50), nullable=False)  # llm, tool, retry, policy
    input_data = Column(Text, nullable=True)
    output_data = Column(Text, nullable=True)
    latency_ms = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("Run", back_populates="steps")


class Approval(Base):
    """Pending, approved, or denied high-risk tool execution request."""
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    tool_args = Column(Text, nullable=False)  # JSON string
    status = Column(String(20), default="pending")  # pending, approved, denied
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(String(100), nullable=True)

    run = relationship("Run", back_populates="approvals")


class AuditLog(Base):
    """Immutable audit trail for security and governance (with PII masked)."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    user = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    outcome = Column(String(50), nullable=False)  # allowed, denied, approved, pending, error


class Document(Base):
    """Metadata record for files ingested for RAG retrieval."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # pdf, docx, txt
    file_size = Column(Integer, nullable=False)
    chunk_count = Column(Integer, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    uploader = relationship("User", back_populates="documents")


def get_db() -> Generator:
    """Dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)


def reset_db_engine():
    """Rebinds database engine and SessionLocal to current settings.DATABASE_URL."""
    global engine, SessionLocal
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    event.listen(engine, "connect", set_sqlite_pragma)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_demo_db():
    """
    Initialize demo SQLite database with a sample 'students' table with 10 rows.
    Strictly for read_sql queries.
    """
    if settings.DEMO_DATABASE_URL.startswith("sqlite:///"):
        demo_db_path = Path(settings.DEMO_DATABASE_URL.replace("sqlite:///", "")).resolve()
    else:
        demo_db_path = (Path(settings.DATA_DIR) / "demo.db").resolve()
    demo_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(demo_db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        marks INTEGER NOT NULL DEFAULT 85,
        gpa REAL NOT NULL,
        graduation_year INTEGER NOT NULL
    );
    """)

    # Check if empty, insert 10 sample records
    cursor.execute("SELECT COUNT(*) FROM students;")
    count = cursor.fetchone()[0]
    if count == 0:
        sample_students = [
            (1, "Aarav Sharma", "Computer Science", 88, 3.85, 2025),
            (2, "Diya Patel", "Electronics", 82, 3.72, 2024),
            (3, "Rohan Iyer", "Mechanical", 75, 3.40, 2025),
            (4, "Ananya Sen", "Computer Science", 95, 3.92, 2024),
            (5, "Kabir Verma", "Civil Engineering", 70, 3.25, 2026),
            (6, "Meera Nair", "Biotechnology", 89, 3.88, 2025),
            (7, "Vikram Joshi", "Computer Science", 84, 3.65, 2024),
            (8, "Pooja Hegde", "Data Science", 96, 3.95, 2026),
            (9, "Arjun Reddy", "Mechanical", 68, 3.10, 2025),
            (10, "Sneha Kulkarni", "Data Science", 86, 3.78, 2024),
        ]
        cursor.executemany(
            "INSERT INTO students (id, name, department, marks, gpa, graduation_year) VALUES (?, ?, ?, ?, ?, ?);",
            sample_students,
        )
        conn.commit()
    else:
        # Ensure marks column exists if table was created in an older run
        cursor.execute("PRAGMA table_info(students);")
        cols = [col[1] for col in cursor.fetchall()]
        if "marks" not in cols:
            cursor.execute("ALTER TABLE students ADD COLUMN marks INTEGER NOT NULL DEFAULT 85;")
            marks_map = {1: 88, 2: 82, 3: 75, 4: 95, 5: 70, 6: 89, 7: 84, 8: 96, 9: 68, 10: 86}
            for sid, m in marks_map.items():
                cursor.execute("UPDATE students SET marks = ? WHERE id = ?;", (m, sid))
            conn.commit()

    conn.close()
