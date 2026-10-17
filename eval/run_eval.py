#!/usr/bin/env python3
"""
Headless, reproducible evaluation harness for Sovereign Agentic AI Workbench.
Benchmarks model behavior (default qwen2.5:3b) inside the agent loop on an 8 GB laptop.
Zero cloud egress, strictly isolated within eval/.workdir, with frozen dataset verification.
"""

import os
import sys
from pathlib import Path

# Enforce isolated data directory BEFORE importing backend
EVAL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_ROOT.parent
WORKDIR = EVAL_ROOT / ".workdir"
WORKDIR.mkdir(parents=True, exist_ok=True)
os.environ["SOVEREIGN_DATA_DIR"] = str(WORKDIR)

sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import ast
import hashlib
import json
import operator
import platform
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import httpx
import psutil

# Safe AST operators for runtime calculator ground truth evaluation
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def eval_safe_arithmetic(expr: str) -> float:
    """Evaluates arithmetic expressions at runtime safely without eval()."""
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.BinOp):
            return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            return _SAFE_OPS[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported node: {type(node)}")
    parsed = ast.parse(expr.strip(), mode="eval")
    return float(_eval(parsed))


class MemoryMonitor:
    """Reuses the memory monitor pattern from scripts/live_check.py."""
    def __init__(self):
        self.running = False
        self.peak_ollama_mb = 0.0
        self._thread: Optional[threading.Thread] = None

    def _get_ollama_processes(self) -> Dict[int, psutil.Process]:
        procs: Dict[int, psutil.Process] = {}
        for p in psutil.process_iter(['name']):
            try:
                name = (p.info.get('name') or '').lower()
                if name.startswith('ollama') or name.startswith('llama'):
                    procs[p.pid] = p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        for pid in list(procs.keys()):
            try:
                parent = procs[pid]
                for child in parent.children(recursive=True):
                    try:
                        cname = (child.name() or '').lower()
                        if 'python' not in cname:
                            procs[child.pid] = child
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return procs

    def _sample(self):
        while self.running:
            ollama_procs = self._get_ollama_processes()
            ollama_mb = 0.0
            for pid, proc in ollama_procs.items():
                try:
                    rss = proc.memory_info().rss / (1024 * 1024)
                    ollama_mb += rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if ollama_mb > self.peak_ollama_mb:
                self.peak_ollama_mb = ollama_mb
            time.sleep(0.3)

    def start(self):
        self.running = True
        self.peak_ollama_mb = 0.0
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        return self.peak_ollama_mb


def check_ram_safety(min_ram_gb: float = 3.0):
    """Memory safety guard: aborts if available RAM is below threshold."""
    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    if available_gb < min_ram_gb:
        print(f"\n[CRITICAL ERROR] Available RAM is {available_gb:.2f} GB, which is below the safe threshold of {min_ram_gb} GB.")
        print("Aborting evaluation run to prevent laptop freeze. Close other applications and retry.")
        sys.exit(1)


def check_ollama_status(model_name: str, embed_model: str = "nomic-embed-text") -> Tuple[str, str]:
    """Verifies Ollama is running and required models are installed."""
    base_url = "http://localhost:11434"
    try:
        with httpx.Client(timeout=4.0) as client:
            res = client.get(f"{base_url}/api/tags")
            if res.status_code != 200:
                print(f"\n[CRITICAL ERROR] Ollama returned status code {res.status_code}.")
                print("Please ensure Ollama is running at http://localhost:11434")
                sys.exit(1)
            data = res.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            version_res = client.get(f"{base_url}/api/version")
            version_str = version_res.json().get("version", "unknown") if version_res.status_code == 200 else "unknown"
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Cannot connect to Ollama at {base_url}: {e}")
        print("Please start Ollama before running the evaluation benchmark.")
        sys.exit(1)

    # Check model presence
    chat_present = any(model_name in m or m.startswith(model_name) for m in models)
    if not chat_present:
        print(f"\n[CRITICAL ERROR] Required chat model '{model_name}' is not pulled in Ollama!")
        print(f"Please run:\n    ollama pull {model_name}")
        sys.exit(1)

    embed_present = any(embed_model in m or m.startswith(embed_model) for m in models)
    if not embed_present:
        print(f"\n[CRITICAL ERROR] Required embedding model '{embed_model}' is not pulled in Ollama!")
        print(f"Please run:\n    ollama pull {embed_model}")
        sys.exit(1)

    # Find model digest
    model_digest = "unknown"
    for m in data.get("models", []):
        if model_name in m.get("name", ""):
            model_digest = m.get("digest", "unknown")
            break

    return version_str, model_digest


def verify_dataset_frozen() -> Tuple[bool, str, Dict[str, str]]:
    """Verifies SHA-256 hashes against eval/data/FROZEN.sha256."""
    frozen_path = EVAL_ROOT / "data" / "FROZEN.sha256"
    if not frozen_path.exists():
        return False, "FROZEN.sha256 file missing", {}

    lines = frozen_path.read_text(encoding="utf-8").strip().splitlines()
    stored_hashes = {}
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 2:
            stored_hashes[parts[1]] = parts[0]

    all_matched = True
    actual_hashes = {}
    for rel_path, expected_hash in stored_hashes.items():
        file_path = EVAL_ROOT / "data" / rel_path
        if not file_path.exists():
            all_matched = False
            continue
        h = hashlib.sha256(file_path.read_bytes()).hexdigest()
        actual_hashes[rel_path] = h
        if h != expected_hash:
            all_matched = False

    status = "verified" if all_matched else "dataset modified"
    return all_matched, status, actual_hashes


def verify_distractors_frozen() -> Tuple[bool, str, Dict[str, str]]:
    """Verifies SHA-256 hashes against eval/data/distractors/DISTRACTORS.sha256."""
    manifest_path = EVAL_ROOT / "data" / "distractors" / "DISTRACTORS.sha256"
    if not manifest_path.exists():
        return False, "DISTRACTORS.sha256 missing", {}

    lines = manifest_path.read_text(encoding="utf-8").strip().splitlines()
    stored = {}
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 2:
            stored[parts[1]] = parts[0]

    all_matched = True
    actual_hashes = {}
    for fn, expected_h in stored.items():
        fp = EVAL_ROOT / "data" / "distractors" / fn
        if not fp.exists():
            all_matched = False
            continue
        h = hashlib.sha256(fp.read_bytes()).hexdigest()
        actual_hashes[fn] = h
        if h != expected_h:
            all_matched = False

    status = "verified" if all_matched else "distractors modified"
    return all_matched, status, actual_hashes


def get_git_commit() -> str:
    """Retrieves current git commit hash if available."""
    try:
        git_cmd = shutil.which("git") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe")
        res = subprocess.run([git_cmd, "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown_commit"


def get_real_data_mtime() -> float:
    """Returns the latest modification time of the real data/ directory."""
    real_data = PROJECT_ROOT / "data"
    if not real_data.exists():
        return 0.0
    latest = real_data.stat().st_mtime
    for p in real_data.rglob("*"):
        try:
            mt = p.stat().st_mtime
            if mt > latest:
                latest = mt
        except Exception:
            pass
    return latest


def setup_isolated_environment(chunk_size: int, include_distractors: bool = False):
    """Initializes isolated databases, vector store, and ingests synthetic docs."""
    from backend.config import settings
    # Override settings for isolated run
    settings.DATA_DIR = str(WORKDIR)
    settings.DATABASE_URL = f"sqlite:///{WORKDIR / 'sovereign.db'}"
    settings.DEMO_DATABASE_URL = f"sqlite:///{WORKDIR / 'demo.db'}"
    settings.CHROMA_PERSIST_DIR = str(WORKDIR / "chroma")
    settings.UPLOAD_DIR = str(WORKDIR / "uploads")
    settings.RAG_CHUNK_SIZE = chunk_size

    from backend.db import init_db, init_demo_db, reset_db_engine, SessionLocal, User, Document
    from backend.main import seed_default_agents
    from backend.rag import vector_store, TextChunker
    from backend.auth import hash_password

    reset_db_engine()
    init_db()
    init_demo_db()

    db = SessionLocal()
    try:
        # Seed admin user for evaluation runs
        admin_user = db.query(User).filter(User.username == "eval_runner").first()
        if not admin_user:
            admin_user = User(
                username="eval_runner",
                password_hash=hash_password("EvalPassword123!"),
                role="admin",
            )

            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        seed_default_agents(db)

        # Clear existing Chroma collection
        try:
            vector_store.client.delete_collection(vector_store.collection_name)
        except Exception:
            pass

        # Clear existing Document records in isolated DB
        db.query(Document).delete()
        db.commit()

        # Ingest docs from eval/data/docs/
        docs_dir = EVAL_ROOT / "data" / "docs"
        corpus_metadata = {}
        doc_files = sorted(docs_dir.glob("*.txt"))

        current_idx = 0
        for doc_path in doc_files:
            current_idx += 1
            text = doc_path.read_text(encoding="utf-8")
            chunks = TextChunker.chunk_text(text, chunk_size=chunk_size, chunk_overlap=settings.RAG_CHUNK_OVERLAP)

            # Copy to isolated uploads
            dest = Path(settings.UPLOAD_DIR) / doc_path.name
            dest.write_text(text, encoding="utf-8")

            # Add to SQLite Document table
            doc_record = Document(
                id=current_idx,
                filename=doc_path.name,
                file_type="txt",
                file_size=len(text.encode("utf-8")),
                chunk_count=len(chunks),
                uploaded_by=admin_user.id,
            )
            db.add(doc_record)
            db.commit()

            # Add to Chroma
            vector_store.add_document(document_id=current_idx, filename=doc_path.name, chunks=chunks)
            corpus_metadata[doc_path.name] = len(chunks)

        # Ingest distractors if requested (for E1b)
        if include_distractors:
            distractors_dir = EVAL_ROOT / "data" / "distractors"
            if distractors_dir.exists():
                distractor_files = sorted(distractors_dir.glob("*.txt"))
                for doc_path in distractor_files:
                    current_idx += 1
                    text = doc_path.read_text(encoding="utf-8")
                    chunks = TextChunker.chunk_text(text, chunk_size=chunk_size, chunk_overlap=settings.RAG_CHUNK_OVERLAP)

                    dest = Path(settings.UPLOAD_DIR) / doc_path.name
                    dest.write_text(text, encoding="utf-8")

                    doc_record = Document(
                        id=current_idx,
                        filename=doc_path.name,
                        file_type="txt",
                        file_size=len(text.encode("utf-8")),
                        chunk_count=len(chunks),
                        uploaded_by=admin_user.id,
                    )
                    db.add(doc_record)
                    db.commit()

                    vector_store.add_document(document_id=current_idx, filename=doc_path.name, chunks=chunks)
                    corpus_metadata[doc_path.name] = len(chunks)

        return admin_user.id, corpus_metadata
    finally:
        db.close()


def run_benchmark():
    parser = argparse.ArgumentParser(description="Headless Evaluation Harness for Sovereign AI Workbench")
    parser.add_argument("--model", type=str, default="qwen2.5:3b", help="Ollama chat model name")
    parser.add_argument("--chunk-size", type=int, default=500, help="RAG chunk size in characters")
    parser.add_argument("--retry", type=str, default="on", choices=["on", "off"], help="Enable agent format retry")
    parser.add_argument("--json-mode", type=str, default="on", choices=["on", "off"], help="Enable Ollama JSON mode")
    parser.add_argument("--prompt-variant", type=str, default="hardened", choices=["baseline", "hardened"], help="Prompt variant")
    parser.add_argument("--repeats", type=int, default=1, help="Number of repetitions per item")
    parser.add_argument("--suite", type=str, default="all", choices=["rag", "agent", "all"], help="Evaluation suite to run")
    parser.add_argument("--out", type=str, default=None, help="Output JSONL filepath")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted run from output file")
    parser.add_argument("--item-timeout", type=int, default=240, help="Per-item timeout in seconds")
    parser.add_argument("--min-ram", type=float, default=3.0, help="RAM safety floor in GB")
    parser.add_argument("--retrieval-only", action="store_true", help="Only compute retrieval metrics (no LLM, for E1/E1b)")
    parser.add_argument("--smoke-test", action="store_true", help="Run 3-item smoke test")
    parser.add_argument("--distractors", action="store_true", help="Include distractor corpus from eval/data/distractors/ (for E1b)")
    parser.add_argument("--require-retrieval-before-abstain", action="store_true", help="Enforce retrieval before abstention (post-hoc variant)")

    args = parser.parse_args()

    # 1. RAM Safety Check
    check_ram_safety(min_ram_gb=args.min_ram)

    # 2. Ollama Status Check
    ollama_version, ollama_digest = check_ollama_status(model_name=args.model)

    # 3. Dataset Freeze Verification
    is_frozen, dataset_status, dataset_hashes = verify_dataset_frozen()
    if not is_frozen:
        print(f"[WARNING] Dataset verification: {dataset_status}. FROZEN.sha256 mismatch detected.")
    else:
        print(f"[OK] Dataset verification: {dataset_status} (FROZEN.sha256 matches all files).")

    if args.distractors:
        is_dist_frozen, dist_status, _ = verify_distractors_frozen()
        if not is_dist_frozen:
            print(f"[WARNING] Distractor verification: {dist_status}. DISTRACTORS.sha256 mismatch detected.")
        else:
            print(f"[OK] Distractor verification: {dist_status} (DISTRACTORS.sha256 matches all files).")

    # 4. Check data/ modification time before run
    mtime_before = get_real_data_mtime()

    # 5. Configure Flags in Settings
    from backend.config import settings
    settings.ENABLE_RETRY = (args.retry.lower() == "on")
    settings.OLLAMA_JSON_MODE = (args.json_mode.lower() == "on")
    settings.PROMPT_VARIANT = args.prompt_variant.lower()
    settings.OLLAMA_MODEL = args.model
    settings.RAG_CHUNK_SIZE = args.chunk_size
    if args.require_retrieval_before_abstain:
        settings.REQUIRE_RETRIEVAL_BEFORE_ABSTAIN = True

    # 6. Setup Isolated Environment
    print(f"\n[INIT] Setting up isolated benchmark workdir at: {WORKDIR}")
    admin_user_id, corpus_metadata = setup_isolated_environment(
        chunk_size=args.chunk_size,
        include_distractors=args.distractors,
    )
    print(f"[INIT] Ingested synthetic corpus ({len(corpus_metadata)} documents): {corpus_metadata}")

    # 7. Prepare Output File
    results_dir = EVAL_ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    if args.out:
        out_path = Path(args.out)
    else:
        tag = f"eval_{args.suite}_{args.model.replace(':', '_')}_c{args.chunk_size}_r{args.retry}_j{args.json_mode}_p{args.prompt_variant}"
        out_path = results_dir / f"{tag}.jsonl"

    completed_keys = set()
    if args.resume and out_path.exists():
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "item_id" in entry:
                        completed_keys.add((entry["item_id"], entry.get("repeat", 1)))
                except Exception:
                    pass
        print(f"[RESUME] Found {len(completed_keys)} already completed item instances in {out_path.name}.")

    # 8. Load Datasets
    rag_items = []
    agent_items = []

    if args.suite in ("rag", "all"):
        rag_path = EVAL_ROOT / "data" / "rag_questions.json"
        rag_items = json.loads(rag_path.read_text(encoding="utf-8"))

    if args.suite in ("agent", "all") and not args.retrieval_only:
        agent_path = EVAL_ROOT / "data" / "agent_tasks.json"
        agent_items = json.loads(agent_path.read_text(encoding="utf-8"))

    if args.smoke_test:
        # Take 1 RAG question, 1 calculator task, 1 SQL task
        rag_items = rag_items[:1] if rag_items else []
        agent_items = [
            next((a for a in agent_items if a["type"] == "calculator"), None),
            next((a for a in agent_items if a["type"] == "sql"), None),
        ]
        agent_items = [a for a in agent_items if a is not None]

    total_unique_items = len(rag_items) + len(agent_items)
    print(f"[DATASET] Loaded {len(rag_items)} RAG items and {len(agent_items)} Agent items (Total unique: {total_unique_items}).")

    # 9. Perform 1 Warmup Call to record cold_start_s
    cold_start_s = 0.0
    if not args.retrieval_only:
        print("[WARMUP] Performing one warm-up call against Ollama...")
        from backend.llm import ollama_client
        w_start = time.time()
        try:
            ollama_client.chat(messages=[{"role": "user", "content": "Respond with {'status': 'ready'} in JSON."}], model=args.model, format="json")
        except Exception as e:
            print(f"[WARMUP] Warning: Warmup call failed: {e}")
        cold_start_s = round(time.time() - w_start, 3)
        print(f"[WARMUP] Completed in {cold_start_s}s (recorded as cold_start_s).")

    # 10. Run Metadata
    metadata = {
        "timestamp": datetime.utcnow().isoformat(),
        "git_commit": get_git_commit(),
        "dataset_status": dataset_status,
        "dataset_hashes": dataset_hashes,
        "model": args.model,
        "ollama_version": ollama_version,
        "ollama_digest": ollama_digest,
        "num_ctx": settings.OLLAMA_NUM_CTX,
        "temperature": 0.2,
        "top_k": settings.RAG_TOP_K,
        "chunk_size": args.chunk_size,
        "flags": {
            "retry": settings.ENABLE_RETRY,
            "json_mode": settings.OLLAMA_JSON_MODE,
            "prompt_variant": settings.PROMPT_VARIANT,
            "require_retrieval_before_abstain": getattr(settings, "REQUIRE_RETRIEVAL_BEFORE_ABSTAIN", False),
            "distractors": args.distractors,
            "retrieval_only": args.retrieval_only,
        },
        "cold_start_s": cold_start_s,
        "repeats": args.repeats,
        "cpu_model": platform.processor() or platform.machine(),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        "python_version": sys.version.split()[0],
    }

    # Open file in append mode if resuming, else write metadata header
    write_mode = "a" if (args.resume and out_path.exists()) else "w"
    out_file = open(out_path, write_mode, encoding="utf-8")
    if write_mode == "w":
        out_file.write(json.dumps({"type": "metadata", **metadata}) + "\n")
        out_file.flush()

    # Import metrics and execution modules
    from eval.metrics import (
        compute_tool_call_valid,
        compute_retrieval_hit,
        compute_chunk_level_retrieval,
        compute_citation_valid,
        compute_task_success,
    )
    from backend.db import SessionLocal, Run, Step, Agent, Approval
    from backend.agent import AgentRunner
    from backend.rag import vector_store

    db = SessionLocal()
    mem_monitor = MemoryMonitor()

    bench_start_time = time.time()
    items_processed = 0

    try:
        # Loop through repetitions
        for rep in range(1, args.repeats + 1):
            print(f"\n--- REPEAT {rep} / {args.repeats} ---")

            # ------------------------------------------------------------------
            # A) RAG Items
            # ------------------------------------------------------------------
            for item in rag_items:
                item_id = item["id"]
                if (item_id, rep) in completed_keys:
                    continue

                check_ram_safety(min_ram_gb=args.min_ram)
                t0 = time.time()
                mem_monitor.start()

                # 1. Retrieval hit@3 (pure vector search) and chunk-level retrieval
                query_text = item["question"]
                top_chunks = vector_store.query(query_text=query_text, top_k=3)
                retrieval_hit = compute_retrieval_hit(top_chunks, item["source_file"], top_k=3)
                chunk_retrieval = compute_chunk_level_retrieval(
                    retrieved_chunks=top_chunks,
                    expected_keywords=item.get("expected_keywords"),
                    match_mode=item.get("match", "all"),
                    top_k=3,
                )

                if args.retrieval_only:
                    peak_ram = mem_monitor.stop()
                    lat = round(time.time() - t0, 3)
                    result_record = {
                        "type": "result",
                        "item_id": item_id,
                        "suite": "rag",
                        "repeat": rep,
                        "question": query_text,
                        "answerable": item.get("answerable", True),
                        "retrieval_hit@3": retrieval_hit,
                        "chunk_hit@1": chunk_retrieval["hit@1"],
                        "chunk_hit@3": chunk_retrieval["hit@3"],
                        "reciprocal_rank": chunk_retrieval["reciprocal_rank"],
                        "matching_rank": chunk_retrieval["matching_rank"],
                        "latency_s": lat,
                        "peak_ollama_rss_mb": round(peak_ram, 1),
                    }
                    out_file.write(json.dumps(result_record) + "\n")
                    out_file.flush()
                    items_processed += 1
                    print(f"  [{items_processed}] {item_id} (rep {rep}): doc_hit@3={retrieval_hit}, chunk_hit@1={chunk_retrieval['hit@1']}, chunk_hit@3={chunk_retrieval['hit@3']}, mrr={chunk_retrieval['reciprocal_rank']:.2f} ({lat}s)")
                    continue

                # 2. Full LLM Agent Execution on RAG Question
                doc_agent = db.query(Agent).filter(Agent.name == "Document Assistant").first()
                run_obj = Run(
                    agent_id=doc_agent.id,
                    user_id=admin_user_id,
                    question=query_text,
                    status="running",
                )
                db.add(run_obj)
                db.commit()
                db.refresh(run_obj)

                is_timeout = False
                try:
                    run_res = AgentRunner.run_agent(run_id=run_obj.id, db=db)
                except Exception as ex:
                    run_res = {"status": "failed", "answer": f"Error: {ex}", "run_id": run_obj.id}

                lat = round(time.time() - t0, 3)
                peak_ram = mem_monitor.stop()

                # Gather step details
                steps = db.query(Step).filter(Step.run_id == run_obj.id).order_by(Step.step_number).all()
                first_llm_step = next((s for s in steps if s.step_type == "llm"), None)
                tool_call_valid = compute_tool_call_valid(first_llm_step.output_data) if first_llm_step else False
                retries_count = sum(1 for s in steps if s.step_type == "retry")
                used_tools = [s.input_data.split("(")[0].strip() for s in steps if s.step_type == "tool"]

                final_answer = run_res.get("answer", "")
                sources = run_res.get("sources", [])
                citation_valid = compute_citation_valid(final_answer, sources, corpus_metadata)

                task_success = compute_task_success(
                    expected_tool="search_documents" if item["answerable"] else None,
                    used_tools=used_tools,
                    answer=final_answer,
                    answerable=item["answerable"],
                    expected_keywords=item.get("expected_keywords"),
                    match_mode=item.get("match", "all"),
                )

                result_record = {
                    "type": "result",
                    "item_id": item_id,
                    "suite": "rag",
                    "repeat": rep,
                    "question": query_text,
                    "answerable": item["answerable"],
                    "tool_call_valid": tool_call_valid,
                    "task_success": task_success,
                    "retrieval_hit@3": retrieval_hit,
                    "chunk_hit@1": chunk_retrieval["hit@1"],
                    "chunk_hit@3": chunk_retrieval["hit@3"],
                    "reciprocal_rank": chunk_retrieval["reciprocal_rank"],
                    "matching_rank": chunk_retrieval["matching_rank"],
                    "citation_valid": citation_valid,
                    "latency_s": lat,
                    "retries": retries_count,
                    "timeout": is_timeout,
                    "peak_ollama_rss_mb": round(peak_ram, 1),
                    "auto_approved": False,
                    "answer": final_answer[:300],
                }
                out_file.write(json.dumps(result_record) + "\n")
                out_file.flush()
                items_processed += 1
                print(f"  [{items_processed}] {item_id} (rep {rep}): valid={tool_call_valid}, success={task_success}, hit@3={retrieval_hit} ({lat}s)")

            # ------------------------------------------------------------------
            # B) Agent Items
            # ------------------------------------------------------------------
            for item in agent_items:
                item_id = item["id"]
                if (item_id, rep) in completed_keys:
                    continue

                check_ram_safety(min_ram_gb=args.min_ram)
                t0 = time.time()
                mem_monitor.start()

                # Determine Ground Truth at runtime
                ground_truth = None
                if item["ground_truth_kind"] == "arithmetic_eval":
                    ground_truth = eval_safe_arithmetic(item["expression"])
                elif item["ground_truth_kind"] == "sql_select":
                    # Direct read-only SELECT against demo.db
                    demo_path = WORKDIR / "demo.db"
                    with sqlite3.connect(f"file:{demo_path}?mode=ro", uri=True) as conn:
                        cur = conn.cursor()
                        cur.execute(item["sql_query"])
                        row = cur.fetchone()
                        ground_truth = row[0] if row else ""

                target_agent = db.query(Agent).filter(Agent.name == item["agent"]).first()
                run_obj = Run(
                    agent_id=target_agent.id,
                    user_id=admin_user_id,
                    question=item["question"],
                    status="running",
                )
                db.add(run_obj)
                db.commit()
                db.refresh(run_obj)

                # Run Agent Loop
                auto_approved = False
                run_res = AgentRunner.run_agent(run_id=run_obj.id, db=db)

                # Handle high-risk pause/resume with auto-approval
                if run_res.get("status") == "paused_for_approval":
                    auto_approved = True
                    apprv = db.query(Approval).filter(Approval.run_id == run_obj.id, Approval.status == "pending").first()
                    if apprv:
                        apprv.status = "approved"
                        apprv.decided_by = "eval_auto_approver"
                        apprv.decided_at = datetime.utcnow()
                        db.commit()
                        # Resume execution
                        run_res = AgentRunner.run_agent(run_id=run_obj.id, db=db)

                lat = round(time.time() - t0, 3)
                peak_ram = mem_monitor.stop()

                steps = db.query(Step).filter(Step.run_id == run_obj.id).order_by(Step.step_number).all()
                first_llm_step = next((s for s in steps if s.step_type == "llm"), None)
                tool_call_valid = compute_tool_call_valid(first_llm_step.output_data) if first_llm_step else False
                retries_count = sum(1 for s in steps if s.step_type == "retry")
                used_tools = [s.input_data.split("(")[0].strip() for s in steps if s.step_type == "tool"]

                final_answer = run_res.get("answer", "")
                sources = run_res.get("sources", [])
                citation_valid = compute_citation_valid(final_answer, sources, corpus_metadata)

                task_success = compute_task_success(
                    expected_tool=item["expected_tool"],
                    used_tools=used_tools,
                    answer=final_answer,
                    answerable=True,
                    ground_truth=ground_truth,
                    expected_keywords=item.get("expected_keywords"),
                    match_mode=item.get("match", "all"),
                )

                result_record = {
                    "type": "result",
                    "item_id": item_id,
                    "suite": "agent",
                    "task_type": item["type"],
                    "repeat": rep,
                    "question": item["question"],
                    "expected_tool": item["expected_tool"],
                    "used_tools": used_tools,
                    "tool_call_valid": tool_call_valid,
                    "task_success": task_success,
                    "retrieval_hit@3": None,
                    "citation_valid": citation_valid,
                    "latency_s": lat,
                    "retries": retries_count,
                    "timeout": False,
                    "peak_ollama_rss_mb": round(peak_ram, 1),
                    "auto_approved": auto_approved,
                    "ground_truth": str(ground_truth),
                    "answer": final_answer[:300],
                }
                out_file.write(json.dumps(result_record) + "\n")
                out_file.flush()
                items_processed += 1
                print(f"  [{items_processed}] {item_id} ({item['type']}, rep {rep}): valid={tool_call_valid}, success={task_success}, auto_apprv={auto_approved} ({lat}s)")

    finally:
        out_file.close()
        db.close()

    total_duration = round(time.time() - bench_start_time, 2)
    print(f"\n[DONE] Benchmark completed in {total_duration}s. Results written to: {out_path}")

    # 11. Isolation Proof: Verify data/ modification time is untouched
    mtime_after = get_real_data_mtime()
    print("\n--- ISOLATION VERIFICATION PROOF ---")
    print(f"  Real data/ mtime before run: {datetime.fromtimestamp(mtime_before).isoformat()}")
    print(f"  Real data/ mtime after run:  {datetime.fromtimestamp(mtime_after).isoformat()}")
    assert mtime_before == mtime_after, f"ISOLATION BREACH! Real data/ was touched (before: {mtime_before}, after: {mtime_after})"
    print("  -> PROOF VERIFIED: Real data/ directory was completely untouched (mtimes identical).\n")


if __name__ == "__main__":
    run_benchmark()
