"""
FastAPI application for Sovereign On-Premise Agentic AI Workbench.
Exposes REST endpoints for Auth, Documents, Agents, Runs, Approvals, Audit Logs, and Health.
Zero cloud egress, strict offline execution.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from contextlib import asynccontextmanager
from backend.config import settings
from backend.db import (
    init_db,
    init_demo_db,
    get_db,
    SessionLocal,
    User,
    Agent,
    Run,
    Step,
    Approval,
    AuditLog,
    Document,
)
from backend.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
)
from backend.llm import ollama_client
from backend.rag import DocumentParser, TextChunker, vector_store
from backend.agent import AgentRunner
from backend.tools import tool_registry
from backend.audit import log_audit_event


def seed_default_agents(db):
    """Seed Document Assistant and Data Analyst default agents if missing, and sync model to settings."""
    doc_prompt = (
        "You are a helpful Document Assistant. You answer questions strictly based on "
        "uploaded files and documents. Always use the search_documents tool to retrieve "
        "context before answering, or use read_file for known files. For any calculation, percentage, "
        "or arithmetic question, you MUST call the calculator tool first. Never compute math in your head. "
        "Always cite your sources with filename and chunk index. If the documents do not contain "
        "the answer, clearly state that you do not know based on the provided documents."
    )
    doc_agent = db.query(Agent).filter(Agent.name == "Document Assistant").first()
    if not doc_agent:
        doc_agent = Agent(
            name="Document Assistant",
            system_prompt=doc_prompt,
            model=settings.OLLAMA_MODEL,
            allowed_tools=json.dumps(["search_documents", "read_file", "calculator"]),
            temperature=0.2,
        )
        db.add(doc_agent)
    else:
        doc_agent.system_prompt = doc_prompt
        if doc_agent.model != settings.OLLAMA_MODEL:
            doc_agent.model = settings.OLLAMA_MODEL

    analyst_agent = db.query(Agent).filter(Agent.name == "Data Analyst").first()
    if not analyst_agent:
        analyst_agent = Agent(
            name="Data Analyst",
            system_prompt=(
                "You are a meticulous Data Analyst. You answer analytical questions by inspecting the "
                "database. Always use the read_sql tool to query the students table or calculator to "
                "compute statistics. Note that read_sql is a high-risk tool requiring supervisor approval."
            ),
            model=settings.OLLAMA_MODEL,
            allowed_tools=json.dumps(["read_sql", "calculator"]),
            temperature=0.1,
        )
        db.add(analyst_agent)
    else:
        if analyst_agent.model != settings.OLLAMA_MODEL:
            analyst_agent.model = settings.OLLAMA_MODEL
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases, seed demo table, register default agents, and clean up orphaned runs."""
    init_db()
    init_demo_db()
    db = SessionLocal()
    try:
        seed_default_agents(db)
        # Mark any orphaned runs from unexpected server restart/shutdown as failed
        orphaned = db.query(Run).filter(Run.status == "running").all()
        for r in orphaned:
            r.status = "failed"
            r.final_answer = "Run was interrupted by server restart or shutdown."
        if orphaned:
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(
    title="Sovereign On-Premise Agentic AI Workbench",
    version="1.0.0",
    description="Offline, secure, privacy-first AI agent workbench.",
    lifespan=lifespan,
)

# Enable CORS for local Streamlit UI communication with explicit local origins
ALLOWED_CORS_ORIGINS = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    """Ensure unexpected runtime exceptions never leak internal paths or stack traces."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please contact administrator."},
    )


# ==============================================================================
# Pydantic Request / Response Schemas
# ==============================================================================

class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str


class AgentCreateRequest(BaseModel):
    name: str
    system_prompt: str
    model: Optional[str] = None
    allowed_tools: List[str]
    temperature: Optional[float] = 0.2


class AgentResponse(BaseModel):
    id: int
    name: str
    system_prompt: str
    model: str
    allowed_tools: List[str]
    temperature: float
    created_at: datetime


class RunRequest(BaseModel):
    question: str


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approve" or "deny"




# ==============================================================================
# 1. Health Endpoint
# ==============================================================================

@app.get("/health", tags=["System"])
def health_check():
    """Checks whether Ollama is reachable and whether configured models are present."""
    ollama_status = ollama_client.check_health()
    is_healthy = (
        ollama_status.get("reachable", False)
        and ollama_status.get("chat_model_present", False)
        and ollama_status.get("embed_model_present", False)
    )
    return {
        "status": "healthy" if is_healthy else "degraded",
        "system": "Sovereign On-Premise Agentic AI Workbench",
        "timestamp": datetime.utcnow().isoformat(),
        "ollama": ollama_status,
    }


# ==============================================================================
# 2. Authentication Endpoints
# ==============================================================================

@app.post("/auth/register", response_model=AuthResponse, tags=["Auth"])
def register(req: AuthRequest, db: Session = Depends(get_db)):
    """
    Register a new user. The very first user to register automatically becomes 'admin'.
    Subsequent users receive the 'user' role.
    """
    cleaned_username = req.username.strip().lower()
    if not cleaned_username or not req.password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password cannot be empty.",
        )

    if len(req.password.strip()) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    existing = db.query(User).filter(User.username == cleaned_username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{cleaned_username}' is already registered.",
        )

    # First user is admin
    user_count = db.query(User).count()
    assigned_role = "admin" if user_count == 0 else "user"

    new_user = User(
        username=cleaned_username,
        password_hash=hash_password(req.password),
        role=assigned_role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit_event(
        user=new_user.username,
        action="user_registered",
        outcome="success",
        details=f"User '{new_user.username}' created with role '{assigned_role}'.",
        db=db,
    )

    token = create_access_token({"sub": new_user.username, "role": new_user.role})
    return AuthResponse(
        access_token=token,
        user_id=new_user.id,
        username=new_user.username,
        role=new_user.role,
    )


@app.post("/auth/login", response_model=AuthResponse, tags=["Auth"])
def login(req: AuthRequest, db: Session = Depends(get_db)):
    """Authenticate with username and password, returning a JWT bearer token."""
    cleaned_username = req.username.strip().lower()
    user = db.query(User).filter(User.username == cleaned_username).first()

    if not user or not verify_password(req.password, user.password_hash):
        log_audit_event(
            user=cleaned_username,
            action="login_failed",
            outcome="unauthorized",
            details="Invalid username or password supplied.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    log_audit_event(
        user=user.username,
        action="login_success",
        outcome="success",
        details="User authenticated successfully.",
        db=db,
    )

    token = create_access_token({"sub": user.username, "role": user.role})
    return AuthResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@app.get("/auth/me", tags=["Auth"])
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Return identity and role of the currently authenticated user."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


# ==============================================================================
# 3. Document Management & RAG Ingestion Endpoints
# ==============================================================================

@app.post("/documents/upload", tags=["Documents"])
def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a document (PDF, DOCX, TXT), extract text, split into chunks,
    embed with nomic-embed-text, and store in Chroma with metadata citations.
    """
    allowed_exts = [".pdf", ".docx", ".txt"]
    file_path_obj = Path(file.filename)
    ext = file_path_obj.suffix.lower()

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Allowed: {', '.join(allowed_exts)}",
        )

    # Sanitize filename
    safe_filename = Path(file.filename).name

    # Check for duplicate filename in knowledge base
    existing = db.query(Document).filter(Document.filename == safe_filename).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A document with filename '{safe_filename}' already exists.",
        )

    # Read and validate content size
    try:
        content = file.file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {str(e)}")

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File exceeds maximum allowed size of 10 MB.",
        )

    save_dest = Path(settings.UPLOAD_DIR) / safe_filename

    # Save file to uploads directory
    try:
        save_dest.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file to disk: {str(e)}")

    # Extract text with guaranteed cleanup on failure
    try:
        raw_text = DocumentParser.extract_text(save_dest)
    except Exception as e:
        if save_dest.exists():
            save_dest.unlink()
        raise HTTPException(status_code=400, detail=f"Failed to extract text: {str(e)}")

    if not raw_text.strip():
        if save_dest.exists():
            save_dest.unlink()
        raise HTTPException(status_code=400, detail="Uploaded document contains no readable text.")

    # Chunk text
    chunks = TextChunker.chunk_text(raw_text)

    # Persist document metadata in SQLite
    doc_record = Document(
        filename=safe_filename,
        file_type=ext.lstrip("."),
        file_size=len(content),
        chunk_count=len(chunks),
        uploaded_by=current_user.id,
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)

    # Ingest chunks into Chroma
    try:
        vector_store.add_document(
            document_id=doc_record.id,
            filename=safe_filename,
            chunks=chunks,
        )
    except Exception as e:
        # Chroma or embedding failed
        log_audit_event(
            user=current_user.username,
            action="document_ingestion_failed",
            outcome="error",
            details=f"Document {safe_filename} embedding error: {str(e)}",
            db=db,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Document text saved, but vector embedding failed: {str(e)}. Ensure Ollama nomic-embed-text is available.",
        )

    log_audit_event(
        user=current_user.username,
        action="document_uploaded",
        outcome="success",
        details=f"File '{safe_filename}' ({len(chunks)} chunks) ingested successfully.",
        db=db,
    )

    return {
        "status": "success",
        "document_id": doc_record.id,
        "filename": safe_filename,
        "chunks": len(chunks),
        "file_size": len(content),
    }


@app.get("/documents", tags=["Documents"])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all uploaded documents."""
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "file_size": d.file_size,
            "chunk_count": d.chunk_count,
            "uploaded_by": d.uploaded_by,
            "created_at": d.created_at.isoformat(),
        }
        for d in docs
    ]


@app.delete("/documents/{document_id}", tags=["Documents"])
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a document, removing its chunks from Chroma and its file from disk.
    Admins can delete any document; regular users can only delete their own.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if current_user.role != "admin" and doc.uploaded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You can only delete your own documents.",
        )

    # 1. Remove vector chunks from Chroma
    vector_store.delete_document(doc.id, doc.filename)

    # 2. Remove file from disk
    file_path = Path(settings.UPLOAD_DIR) / doc.filename
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass

    # 3. Remove from database
    filename = doc.filename
    db.delete(doc)
    db.commit()

    log_audit_event(
        user=current_user.username,
        action="document_deleted",
        outcome="success",
        details=f"Document '{filename}' (ID: {document_id}) deleted.",
        db=db,
    )

    return {
        "status": "success",
        "message": f"Document '{filename}' deleted successfully.",
        "document_id": document_id,
    }


# ==============================================================================
# 4. Agent Management Endpoints
# ==============================================================================

@app.post("/agents", response_model=AgentResponse, tags=["Agents"])
def create_agent(
    req: AgentCreateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only: Create a new custom agent with specific allowed tools."""
    cleaned_name = req.name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="Agent name is required.")

    if req.temperature is not None and (req.temperature < 0.0 or req.temperature > 1.0):
        raise HTTPException(status_code=400, detail="Temperature must be between 0.0 and 1.0.")

    existing = db.query(Agent).filter(Agent.name == cleaned_name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Agent with name '{cleaned_name}' already exists.",
        )

    # Validate that all requested tools exist in registry
    registered_tools = [t.name for t in tool_registry.list_all()]
    for t_name in req.allowed_tools:
        if t_name not in registered_tools:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool '{t_name}'. Registered tools: {', '.join(registered_tools)}",
            )

    agent = Agent(
        name=cleaned_name,
        system_prompt=req.system_prompt,
        model=req.model or settings.OLLAMA_MODEL,
        allowed_tools=json.dumps(req.allowed_tools),
        temperature=req.temperature or 0.2,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    log_audit_event(
        user=current_user.username,
        action="agent_created",
        outcome="success",
        details=f"Agent '{agent.name}' created with tools: {req.allowed_tools}",
        db=db,
    )

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        system_prompt=agent.system_prompt,
        model=agent.model,
        allowed_tools=agent.get_allowed_tools_list(),
        temperature=agent.temperature,
        created_at=agent.created_at,
    )


@app.get("/agents", response_model=List[AgentResponse], tags=["Agents"])
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all available agents."""
    agents = db.query(Agent).order_by(Agent.id).all()
    return [
        AgentResponse(
            id=a.id,
            name=a.name,
            system_prompt=a.system_prompt,
            model=a.model,
            allowed_tools=a.get_allowed_tools_list(),
            temperature=a.temperature,
            created_at=a.created_at,
        )
        for a in agents
    ]


@app.put("/agents/{agent_id}", response_model=AgentResponse, tags=["Agents"])
def update_agent(
    agent_id: int,
    req: AgentCreateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only: Update an existing agent's configuration."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    cleaned_name = req.name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="Agent name cannot be empty.")

    if req.temperature is not None and (req.temperature < 0.0 or req.temperature > 1.0):
        raise HTTPException(status_code=400, detail="Temperature must be between 0.0 and 1.0.")

    # Check for duplicate name if renaming to another existing agent
    if cleaned_name != agent.name:
        existing = db.query(Agent).filter(Agent.name == cleaned_name).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Agent with name '{cleaned_name}' already exists.",
            )

    registered_tools = [t.name for t in tool_registry.list_all()]
    for t_name in req.allowed_tools:
        if t_name not in registered_tools:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool '{t_name}'. Registered tools: {', '.join(registered_tools)}",
            )

    agent.name = cleaned_name
    agent.system_prompt = req.system_prompt
    if req.model:
        agent.model = req.model.strip()
    agent.allowed_tools = json.dumps(req.allowed_tools)
    if req.temperature is not None:
        agent.temperature = req.temperature

    db.commit()
    db.refresh(agent)

    log_audit_event(
        user=current_user.username,
        action="agent_updated",
        outcome="success",
        details=f"Agent '{agent.name}' (ID: {agent.id}) updated.",
        db=db,
    )

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        system_prompt=agent.system_prompt,
        model=agent.model,
        allowed_tools=agent.get_allowed_tools_list(),
        temperature=agent.temperature,
        created_at=agent.created_at,
    )


@app.get("/users", tags=["Users"])
def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only: List registered users."""
    users = db.query(User).order_by(User.id).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@app.get("/tools", tags=["Tools"])
def list_available_tools(current_user: User = Depends(get_current_user)):
    """List all registered tools with risk levels and schemas."""
    return tool_registry.list_definitions()


# ==============================================================================
# 5. Agent Execution & Runs Endpoints
# ==============================================================================

@app.post("/agents/{agent_id}/run", tags=["Runs"])
def run_agent(
    agent_id: int,
    req: RunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute an agent run for a user question.
    Records steps, latencies, and halts if high-risk approval is required.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found.")

    clean_q = req.question.strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(clean_q) > 8000:
        raise HTTPException(status_code=400, detail="Question exceeds maximum allowed length of 8000 characters.")

    # Guard against rapid repeated clicks creating duplicate concurrent runs
    existing_active = (
        db.query(Run)
        .filter(
            Run.user_id == current_user.id,
            Run.agent_id == agent.id,
            Run.question == clean_q,
            Run.status.in_(["running", "paused_for_approval"]),
        )
        .first()
    )
    if existing_active:
        raise HTTPException(
            status_code=409,
            detail=f"An active run with the identical question is already in progress (Run #{existing_active.id}).",
        )

    # Create run record
    new_run = Run(
        user_id=current_user.id,
        agent_id=agent.id,
        question=clean_q,
        status="running",
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    log_audit_event(
        user=current_user.username,
        action="agent_run_started",
        outcome="started",
        details=f"Run #{new_run.id} initiated on agent '{agent.name}'. Question: {clean_q[:200]}",
        db=db,
    )

    # Execute hand-crafted loop
    result = AgentRunner.run_agent(run_id=new_run.id, db=db)
    return result


@app.get("/runs", tags=["Runs"])
def list_runs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List runs. Admin sees all runs; regular users see only their own runs.
    """
    if current_user.role == "admin":
        runs = db.query(Run).order_by(Run.created_at.desc()).all()
    else:
        runs = (
            db.query(Run)
            .filter(Run.user_id == current_user.id)
            .order_by(Run.created_at.desc())
            .all()
        )

    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "username": r.user.username if r.user else "unknown",
            "agent_id": r.agent_id,
            "agent_name": r.agent.name if r.agent else "unknown",
            "question": r.question,
            "final_answer": r.final_answer,
            "status": r.status,
            "total_latency_ms": r.total_latency_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]


@app.get("/runs/{run_id}", tags=["Runs"])
def get_run_details(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full trace details for a specific run including every step and latency."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    if current_user.role != "admin" and run.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied to this run trace.")

    steps = (
        db.query(Step)
        .filter(Step.run_id == run_id)
        .order_by(Step.step_number)
        .all()
    )

    approvals = (
        db.query(Approval)
        .filter(Approval.run_id == run_id)
        .order_by(Approval.id)
        .all()
    )

    return {
        "id": run.id,
        "user_id": run.user_id,
        "username": run.user.username if run.user else "unknown",
        "agent_id": run.agent_id,
        "agent_name": run.agent.name if run.agent else "unknown",
        "question": run.question,
        "final_answer": run.final_answer,
        "status": run.status,
        "total_latency_ms": run.total_latency_ms,
        "created_at": run.created_at.isoformat(),
        "steps": [
            {
                "step_number": s.step_number,
                "step_type": s.step_type,
                "input_data": s.input_data,
                "output_data": s.output_data,
                "latency_ms": s.latency_ms,
                "created_at": s.created_at.isoformat(),
            }
            for s in steps
        ],
        "approvals": [
            {
                "id": a.id,
                "tool_name": a.tool_name,
                "tool_args": a.tool_args,
                "status": a.status,
                "requested_at": a.requested_at.isoformat(),
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "decided_by": a.decided_by,
            }
            for a in approvals
        ],
    }


# ==============================================================================
# 6. Approvals (Human-in-the-Loop) Endpoints
# ==============================================================================

@app.get("/approvals/pending", tags=["Approvals"])
def list_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List pending high-risk tool execution requests awaiting confirmation.
    Admins see all pending approvals; regular users see only their own.
    """
    query = db.query(Approval).filter(Approval.status == "pending")
    if current_user.role != "admin":
        query = query.join(Run).filter(Run.user_id == current_user.id)
    pending = query.order_by(Approval.requested_at.desc()).all()

    results = []
    for apprv in pending:
        run = db.query(Run).filter(Run.id == apprv.run_id).first()
        results.append({
            "id": apprv.id,
            "run_id": apprv.run_id,
            "tool_name": apprv.tool_name,
            "tool_args": apprv.tool_args,
            "status": apprv.status,
            "requested_at": apprv.requested_at.isoformat(),
            "question": run.question if run else "",
            "username": run.user.username if run and run.user else "",
        })
    return results


@app.post("/approvals/{approval_id}/decide", tags=["Approvals"])
def decide_approval(
    approval_id: int,
    req: ApprovalDecisionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Confirm or deny a high-risk tool request. Resumes the paused agent run.
    Object-level authorization enforced: non-admins cannot decide another user's run.
    """
    decision = req.decision.strip().lower()
    if decision not in ("approve", "deny"):
        raise HTTPException(
            status_code=400,
            detail="Decision must be either 'approve' or 'deny'.",
        )

    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")

    if approval.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Approval request #{approval_id} has already been decided ({approval.status}).",
        )

    run = db.query(Run).filter(Run.id == approval.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Associated run not found.")

    # Only admin or the creator of the run may decide this approval
    if current_user.role != "admin" and run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: You cannot decide approvals for another user's run.",
        )

    # Update approval state
    outcome_status = "approved" if decision == "approve" else "denied"
    approval.status = outcome_status
    approval.decided_at = datetime.utcnow()
    approval.decided_by = current_user.username
    db.commit()

    log_audit_event(
        user=current_user.username,
        action=f"approval_decision:{approval.tool_name}",
        outcome=outcome_status,
        details=f"Approval #{approval.id} for Run #{run.id} decided as '{outcome_status}'.",
        db=db,
    )

    # Resume the agent execution loop!
    resume_result = AgentRunner.run_agent(run_id=run.id, db=db)
    return {
        "status": "resumed",
        "approval_id": approval.id,
        "decision": outcome_status,
        "run_result": resume_result,
    }


# ==============================================================================
# 7. Audit Log Endpoint (Admin Only)
# ==============================================================================

@app.get("/audit", tags=["Audit"])
def get_audit_logs(
    user: Optional[str] = None,
    action: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 200,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin-only: Retrieve security and governance audit logs with masked PII.
    Supports filtering by user, action, and outcome.
    """
    query = db.query(AuditLog)
    if user:
        query = query.filter(AuditLog.user == user.strip().lower())
    if action:
        query = query.filter(AuditLog.action.contains(action.strip()))
    if outcome:
        query = query.filter(AuditLog.outcome == outcome.strip().lower())

    logs = query.order_by(AuditLog.timestamp.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "user": log.user,
            "action": log.action,
            "details": log.details,
            "outcome": log.outcome,
        }
        for log in logs
    ]
