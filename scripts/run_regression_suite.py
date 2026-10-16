"""
Live Regression Test Suite Runner for Stage 5.
Executes the 15 regression prompts live against native Ollama (qwen2.5:3b & nomic-embed-text).
Outputs results with tool chosen, correctness, JSON first try, retries, citations, and latencies.
"""

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings
from backend.db import Base, SessionLocal, engine, Agent, User, Run, Step, Document, init_db, init_demo_db
from backend.agent import AgentRunner
from backend.rag import vector_store, TextChunker
from backend.llm import ollama_client


def setup_knowledge_base(db):
    """Provisions a reference document in the knowledge base and demo database."""
    init_db()
    init_demo_db()

    # Create admin user if not present
    user = db.query(User).filter(User.username == "regression_tester").first()
    if not user:
        from backend.auth import hash_password
        user = User(username="regression_tester", password_hash=hash_password("Password123!"), role="admin")
        db.add(user)
        db.commit()
        db.refresh(user)

    # Create full-power agent with all tools
    agent = db.query(Agent).filter(Agent.name == "Regression Specialist").first()
    if not agent:
        agent = Agent(
            name="Regression Specialist",
            system_prompt=(
                "You are an expert AI assistant on an on-premise sovereign system. "
                "You can search documents, perform exact calculations, and query the SQL database. "
                "Always choose the best tool to answer accurately."
            ),
            model=settings.OLLAMA_MODEL,
            allowed_tools=json.dumps(["search_documents", "calculator", "read_sql"]),
            temperature=0.1,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

    # Provision reference document
    spec_text = (
        "Project Orion was founded in 2024 to design sovereign on-premise AI systems "
        "for air-gapped defense and enterprise installations.\n\n"
        "The deployment specification mandates exactly 3 replica nodes with 8 GB RAM each "
        "running locally without internet access.\n\n"
        "All user passwords and authentication tokens are secured using bcrypt hashes and "
        "AES-256 encrypted local persistence in the architecture document."
    )

    doc_filename = "sovereign_specs.txt"
    doc_path = Path(settings.UPLOAD_DIR) / doc_filename
    doc_path.write_text(spec_text, encoding="utf-8")

    doc_record = db.query(Document).filter(Document.filename == doc_filename).first()
    if not doc_record:
        chunks = TextChunker.chunk_text(spec_text, chunk_size=300, chunk_overlap=50)
        doc_record = Document(
            filename=doc_filename,
            file_type="txt",
            file_size=len(spec_text.encode("utf-8")),
            chunk_count=len(chunks),
            uploaded_by=user.id,
        )
        db.add(doc_record)
        db.commit()
        db.refresh(doc_record)
    else:
        chunks = TextChunker.chunk_text(spec_text, chunk_size=300, chunk_overlap=50)
    vector_store.delete_document(doc_record.id, filename=doc_filename)
    vector_store.add_document(
        document_id=doc_record.id,
        filename=doc_filename,
        chunks=chunks,
    )

    return user, agent


def run_suite():
    print("=" * 70)
    print("STAGE 5: LIVE REGRESSION TEST SUITE (qwen2.5:3b + nomic-embed-text)")
    print("=" * 70)

    # Verify Ollama
    health = ollama_client.check_health()
    if not health.get("reachable"):
        print(f"ERROR: Ollama is unreachable at {health.get('base_url')}")
        sys.exit(1)
    print(f"Ollama reachable: True | Model: {settings.OLLAMA_MODEL} | Embed: {settings.OLLAMA_EMBED_MODEL}")

    db = SessionLocal()
    user, agent = setup_knowledge_base(db)

    prompts_path = PROJECT_ROOT / "tests" / "regression_prompts.json"
    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    results = []

    for idx, item in enumerate(prompts, start=1):
        prompt_id = item["id"]
        category = item["category"]
        prompt_text = item["prompt"]
        expected_tool = item["expected_tool"]
        keywords = item["expected_keywords"]
        req_citation = item["requires_citation"]

        print(f"\n[{idx}/15] [{category}] {prompt_id}")
        print(f"  Prompt: {prompt_text}")

        # Create Run record
        run = Run(
            user_id=user.id,
            agent_id=agent.id,
            question=prompt_text,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        t_start = time.time()
        agent_result = AgentRunner.run_agent(run_id=run.id, db=db, max_iterations=4)

        # If policy paused for high-risk approval (e.g. read_sql), approve and resume as admin
        if agent_result.get("status") == "paused_for_approval":
            app_id = agent_result.get("approval_id")
            from backend.db import Approval
            from datetime import datetime
            approval = db.query(Approval).filter(Approval.id == app_id).first()
            if approval:
                approval.status = "approved"
                approval.decided_at = datetime.utcnow()
                approval.decided_by = user.username
                db.commit()
                print(f"  [Policy HIT] Paused for approval #{app_id} on {approval.tool_name} -> Approved by {user.username}. Resuming...")
                agent_result = AgentRunner.run_agent(run_id=run.id, db=db, max_iterations=4)

        total_lat = (time.time() - t_start) * 1000

        # Query steps to inspect tools, retries, and citations
        steps = db.query(Step).filter(Step.run_id == run.id).order_by(Step.step_number).all()
        tools_called = [s.input_data.split("(")[0] for s in steps if s.step_type == "tool"]
        retries_count = len([s for s in steps if s.step_type == "retry"])
        json_first_try = (retries_count == 0)

        primary_tool = tools_called[0] if tools_called else "none"
        final_answer = agent_result.get("answer", "")

        # Check correctness
        correct_keywords = any(kw.lower() in final_answer.lower() for kw in keywords)
        if category == "not_in_documents":
            correct_tool = (primary_tool in [expected_tool, "none"])
        else:
            correct_tool = (primary_tool == expected_tool) if expected_tool else True
        is_correct = correct_keywords and correct_tool

        # Check citation
        citation_valid = False
        if req_citation:
            if "sovereign_specs.txt" in final_answer or any("sovereign_specs.txt" in str(s) for s in agent_result.get("sources", [])):
                citation_valid = True
        else:
            citation_valid = True  # Not required

        res_entry = {
            "id": prompt_id,
            "category": category,
            "prompt": prompt_text,
            "expected_tool": expected_tool,
            "tool_chosen": primary_tool,
            "all_tools": tools_called,
            "correct": is_correct,
            "json_first_try": json_first_try,
            "retries": retries_count,
            "citation_correct": citation_valid,
            "latency_ms": round(total_lat, 1),
            "answer_preview": final_answer[:120].replace("\n", " "),
        }
        results.append(res_entry)

        status_str = "PASS" if (is_correct and citation_valid and json_first_try) else "WARN/FAIL"
        print(f"  Tool: {primary_tool} (expected {expected_tool}) | JSON 1st Try: {json_first_try} | Retries: {retries_count}")
        print(f"  Citation Valid: {citation_valid} | Correct: {is_correct} | Latency: {round(total_lat, 1)}ms | Result: {status_str}")
        print(f"  Answer: {final_answer[:150]}...")

    db.close()

    # Save results
    out_filename = sys.argv[1] if len(sys.argv) > 1 else "docs/regression_results.json"
    out_path = PROJECT_ROOT / out_filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print("REGRESSION SUMMARY")
    print("=" * 70)
    print(f"{'ID':<25} | {'Tool':<15} | {'1st JSON':<8} | {'Retries':<7} | {'Cite':<5} | {'Correct':<7} | {'Latency':<8}")
    print("-" * 85)
    for r in results:
        print(f"{r['id']:<25} | {r['tool_chosen']:<15} | {str(r['json_first_try']):<8} | {r['retries']:<7} | {str(r['citation_correct']):<5} | {str(r['correct']):<7} | {r['latency_ms']:<8}")

    passed = sum(1 for r in results if r['correct'] and r['citation_correct'])
    first_try_json = sum(1 for r in results if r['json_first_try'])
    avg_lat = sum(r['latency_ms'] for r in results) / len(results)
    print("-" * 85)
    print(f"Total: {len(results)} | Accuracy: {passed}/{len(results)} ({round(passed/len(results)*100, 1)}%) | JSON 1st Try: {first_try_json}/{len(results)} | Avg Latency: {round(avg_lat, 1)}ms")
    print(f"Saved results to {out_path}")


if __name__ == "__main__":
    run_suite()
