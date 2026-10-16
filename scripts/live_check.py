"""
Live acceptance verification script for Sovereign Workbench.
Connects directly to the running backend (or launches native uvicorn process)
and tests all workflows against the real host Ollama running qwen2.5:3b and nomic-embed-text.

Tracks peak RAM for both Ollama and Backend using psutil.
Supports running 1 or multiple iterations and reports step-by-step pass/fail statistics.
"""

import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager, nullcontext
import httpx
import psutil

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings

BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")


class MemoryMonitor:
    """Monitors peak RAM usage (RSS in MB) for Ollama (including runner processes) and Backend processes."""

    def __init__(self, backend_pid: Optional[int] = None):
        self.backend_pid = backend_pid
        self.running = False
        self.peak_ollama_mb = 0.0
        self.peak_backend_mb = 0.0
        self.peak_ollama_breakdown: List[Tuple[str, int, float]] = []
        self.is_generating = False
        self.current_step = ""
        self._thread: Optional[threading.Thread] = None

    @contextmanager
    def track_chat(self, step_name: str = ""):
        """Context manager to flag active chat generation for per-process RSS output."""
        self.is_generating = True
        self.current_step = step_name
        try:
            yield
        finally:
            self.is_generating = False
            self.current_step = ""

    def _get_ollama_processes(self) -> Dict[int, psutil.Process]:
        """Finds all processes starting with 'ollama' or 'llama', plus all recursive child runner processes."""
        procs: Dict[int, psutil.Process] = {}
        for p in psutil.process_iter(['name']):
            try:
                name = (p.info.get('name') or '').lower()
                if name.startswith('ollama') or name.startswith('llama'):
                    procs[p.pid] = p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Include child processes (e.g. llama-server.exe child processes spawned by ollama)
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
            # 1. Ollama memory: sum of ALL processes whose name starts with ollama (including runner child processes)
            ollama_procs = self._get_ollama_processes()
            ollama_mb = 0.0
            current_ollama_list = []
            for pid, proc in ollama_procs.items():
                try:
                    rss = proc.memory_info().rss / (1024 * 1024)
                    ollama_mb += rss
                    current_ollama_list.append((proc.name(), pid, rss))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if ollama_mb > self.peak_ollama_mb:
                self.peak_ollama_mb = ollama_mb
                self.peak_ollama_breakdown = sorted(current_ollama_list, key=lambda x: x[2], reverse=True)

            # Print per-process RSS while a chat is actively generating so user sees which process holds the model
            if self.is_generating and current_ollama_list:
                sorted_list = sorted(current_ollama_list, key=lambda x: x[2], reverse=True)
                breakdown = ", ".join(f"{name} (PID {pid}): {rss:.1f} MB" for name, pid, rss in sorted_list)
                step_tag = f" [{self.current_step}]" if self.current_step else ""
                print(f"    [RAM Monitor{step_tag}] Ollama Sum RSS: {ollama_mb:.1f} MB -> [{breakdown}]")

            # 2. Backend memory: by PID or finding uvicorn / main.py
            backend_mb = 0.0
            if self.backend_pid:
                try:
                    p = psutil.Process(self.backend_pid)
                    backend_mb += p.memory_info().rss / (1024 * 1024)
                    for child in p.children(recursive=True):
                        backend_mb += child.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            else:
                for proc in psutil.process_iter(['name', 'cmdline', 'memory_info']):
                    try:
                        cmdline = " ".join(proc.info.get('cmdline') or []).lower()
                        if 'backend.main' in cmdline or 'uvicorn' in cmdline:
                            backend_mb += proc.info['memory_info'].rss / (1024 * 1024)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            if backend_mb > self.peak_backend_mb:
                self.peak_backend_mb = backend_mb

            time.sleep(0.5)

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)


def is_port_listening(host: str = "127.0.0.1", port: int = 8000) -> bool:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def ensure_backend_running() -> Tuple[bool, Optional[subprocess.Popen]]:
    """Checks if backend is reachable at BACKEND_BASE_URL; if not, starts it."""
    if is_port_listening("127.0.0.1", 8000):
        print(f"[INIT] Backend is already active on port 8000 ({BACKEND_BASE_URL})")
        return True, None

    print(f"[INIT] Launching backend server at {BACKEND_BASE_URL}...")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
    for _ in range(30):
        time.sleep(0.5)
        if is_port_listening("127.0.0.1", 8000):
            print(f"[INIT] Backend started successfully (PID: {proc.pid})")
            return True, proc

    print("[ERROR] Failed to start backend within 15 seconds.")
    proc.terminate()
    return False, None


def reset_test_state():
    """Resets SQLite records and Chroma vectors cleanly without table drops."""
    from backend.db import SessionLocal, Step, Run, Approval, AuditLog, Document, User, init_demo_db
    from backend.main import seed_default_agents
    from backend.rag import vector_store

    init_demo_db()
    db = SessionLocal()
    try:
        db.query(Step).delete()
        db.query(Approval).delete()
        db.query(Run).delete()
        db.query(Document).delete()
        db.query(AuditLog).delete()
        db.query(User).delete()
        db.commit()
        seed_default_agents(db)
    finally:
        db.close()

    try:
        col = vector_store.collection
        res = col.get()
        if res and res.get("ids"):
            col.delete(ids=res["ids"])
    except Exception:
        pass


def run_live_check_iteration(iteration_num: int, mem_monitor: Optional[MemoryMonitor] = None) -> Dict[str, bool]:
    """Runs one complete pass of acceptance checks a) through h)."""
    print(f"\n{'='*70}")
    print(f"  LIVE ACCEPTANCE RUN #{iteration_num}")
    print(f"{'='*70}\n")

    results = {}
    reset_test_state()

    client = httpx.Client(base_url=BACKEND_BASE_URL, timeout=120.0)

    # --------------------------------------------------------------------------
    # Step a) GET /health: Ollama reachable and both models present
    # --------------------------------------------------------------------------
    print("--- [Step a] GET /health check ---")
    try:
        res = client.get("/health")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        ollama_data = data.get("ollama", {})
        reachable = ollama_data.get("reachable", False)
        chat_present = ollama_data.get("chat_model_present", False)
        embed_present = ollama_data.get("embed_model_present", False)
        configured_chat = ollama_data.get("configured_chat_model")
        configured_embed = ollama_data.get("configured_embed_model")

        print(f"  Ollama Reachable: {reachable}")
        print(f"  Configured Chat Model: '{configured_chat}' (Present: {chat_present})")
        print(f"  Configured Embed Model: '{configured_embed}' (Present: {embed_present})")

        if not reachable:
            print("\n[CRITICAL ERROR] Ollama is unreachable at http://localhost:11434!")
            print("Please run: 'ollama serve' in a separate terminal.")
            results["step_a_health"] = False
            return results

        if not chat_present:
            print(f"\n[CRITICAL ERROR] Model '{configured_chat}' is missing in Ollama!")
            print(f"Please run: 'ollama pull {configured_chat}'")
            results["step_a_health"] = False
            return results

        if not embed_present:
            print(f"\n[CRITICAL ERROR] Model '{configured_embed}' is missing in Ollama!")
            print(f"Please run: 'ollama pull {configured_embed}'")
            results["step_a_health"] = False
            return results

        assert reachable and chat_present and embed_present
        print("  -> PASS: Ollama reachable and both models present.")
        results["step_a_health"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_a_health"] = False
        return results

    # --------------------------------------------------------------------------
    # Step b) Register first user (admin), register second user (user)
    # --------------------------------------------------------------------------
    print("\n--- [Step b] Auth & Roles check ---")
    try:
        ts = int(time.time() * 1000)
        # First user -> must be admin
        u1_res = client.post("/auth/register", json={"username": f"admin_{ts}", "password": "AdminPassword123!"})
        assert u1_res.status_code == 200, f"Registration failed: {u1_res.text}"
        u1_data = u1_res.json()
        assert u1_data["role"] == "admin", f"Expected admin role, got '{u1_data['role']}'"
        admin_token = u1_data["access_token"]
        print(f"  User 1 '{u1_data['username']}' assigned role: {u1_data['role']} (CORRECT: admin)")

        # Second user -> must be user
        u2_res = client.post("/auth/register", json={"username": f"user_{ts}", "password": "UserPassword123!"})
        assert u2_res.status_code == 200, f"Registration failed: {u2_res.text}"
        u2_data = u2_res.json()
        assert u2_data["role"] == "user", f"Expected user role, got '{u2_data['role']}'"
        user_token = u2_data["access_token"]
        print(f"  User 2 '{u2_data['username']}' assigned role: {u2_data['role']} (CORRECT: user)")

        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        user_headers = {"Authorization": f"Bearer {user_token}"}

        print("  -> PASS: First user is admin, second user is user.")
        results["step_b_auth"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_b_auth"] = False
        return results

    # --------------------------------------------------------------------------
    # Step c) Upload TXT about attendance rules
    # --------------------------------------------------------------------------
    print("\n--- [Step c] Upload attendance document ---")
    try:
        doc_content = (
            "University Academic Regulations 2026: The minimum attendance is 75 percent for eligibility "
            "to appear in semester examinations. Students having less than 75 percent attendance will be detained."
        )
        files = {"file": ("attendance_rules.txt", doc_content.encode("utf-8"), "text/plain")}
        up_res = client.post("/documents/upload", headers=user_headers, files=files)
        assert up_res.status_code == 200, f"Upload failed: {up_res.text}"
        up_data = up_res.json()
        print(f"  Uploaded '{up_data['filename']}' ({up_data['chunks']} chunks, doc_id: {up_data['document_id']})")
        assert up_data["chunks"] >= 1
        print("  -> PASS: Document uploaded and ingested into ChromaDB.")
        results["step_c_upload"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_c_upload"] = False
        return results

    # Fetch default agents
    agents_res = client.get("/agents", headers=user_headers)
    agents = agents_res.json()
    doc_agent = next((a for a in agents if a["name"] == "Document Assistant"), None)
    data_agent = next((a for a in agents if a["name"] == "Data Analyst"), None)
    assert doc_agent is not None, "Document Assistant not found"
    assert data_agent is not None, "Data Analyst not found"

    # Helper to print step traces and count retries
    def print_trace_and_retries(run_id: int):
        trace_res = client.get(f"/runs/{run_id}", headers=user_headers)
        if trace_res.status_code == 200:
            trace = trace_res.json()
            steps = trace.get("steps", [])
            retries = [s for s in steps if s["step_type"] == "retry"]
            print(f"    [Trace Summary] Total Steps: {len(steps)} | Retries: {len(retries)}")
            for s in steps:
                st_type = s["step_type"]
                lat = s["latency_ms"]
                print(f"      - Step #{s['step_number']} [{st_type.upper()}] ({lat} ms): {s['input_data'][:120]}")
                if st_type == "retry":
                    print(f"        * Invalid-JSON / Retry output: {s['output_data'][:120]}")
            return len(retries)
        return 0

    # --------------------------------------------------------------------------
    # Step d) Ask Document Assistant: "What is the minimum attendance?"
    # --------------------------------------------------------------------------
    print("\n--- [Step d] Ask Document Assistant: 'What is the minimum attendance?' ---")
    try:
        with (mem_monitor.track_chat("Step d: Doc Assistant") if mem_monitor else nullcontext()):
            run_res = client.post(
                f"/agents/{doc_agent['id']}/run",
                headers=user_headers,
                json={"question": "What is the minimum attendance?"},
            )
        assert run_res.status_code == 200, f"Run call failed: {run_res.text}"
        run_data = run_res.json()
        answer = run_data.get("answer", "")
        run_id = run_data["run_id"]
        sources = run_data.get("sources", [])

        print(f"  Answer: {answer}")
        print(f"  Sources / Citations: {sources}")
        print_trace_and_retries(run_id)

        assert "75" in answer, f"Expected '75' in answer, got: '{answer}'"
        # Check citations
        has_citation = any("attendance_rules.txt" in s for s in sources) or "attendance_rules.txt" in answer or "Source:" in str(sources)
        print(f"  Citation present: {has_citation}")
        assert has_citation, "Citation of attendance_rules.txt missing in sources/answer"

        print("  -> PASS: Document Assistant answered correctly with citation.")
        results["step_d_doc_assistant"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_d_doc_assistant"] = False

    # --------------------------------------------------------------------------
    # Step e) Ask: "What is 15% of 2480?" (confirm calculator tool used)
    # --------------------------------------------------------------------------
    print("\n--- [Step e] Ask Document Assistant: 'What is 15% of 2480?' ---")
    try:
        with (mem_monitor.track_chat("Step e: Calculator") if mem_monitor else nullcontext()):
            calc_res = client.post(
                f"/agents/{doc_agent['id']}/run",
                headers=user_headers,
                json={"question": "What is 15% of 2480?"},
            )
        assert calc_res.status_code == 200, f"Run call failed: {calc_res.text}"
        calc_data = calc_res.json()
        answer = calc_data.get("answer", "")
        run_id = calc_data["run_id"]

        print(f"  Answer: {answer}")
        print_trace_and_retries(run_id)

        # Verify calculator tool step
        trace_res = client.get(f"/runs/{run_id}", headers=user_headers).json()
        tool_steps = [s for s in trace_res.get("steps", []) if s["step_type"] == "tool"]
        calculator_used = any("calculator" in s["input_data"].lower() for s in tool_steps)
        print(f"  Calculator tool used: {calculator_used}")
        assert calculator_used, "Expected calculator tool step in trace"
        assert "372" in answer, f"Expected 372 in answer, got: '{answer}'"

        print("  -> PASS: Calculator tool invoked and correct math answer (372) returned.")
        results["step_e_calculator"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_e_calculator"] = False

    # --------------------------------------------------------------------------
    # Step f) Ask Data Analyst: "List students with marks above 80"
    #         Confirm paused_for_approval -> approve -> final answer
    #         Repeat once with deny -> print answer
    # --------------------------------------------------------------------------
    print("\n--- [Step f1] Data Analyst: 'List students with marks above 80' (Approve path) ---")
    try:
        with (mem_monitor.track_chat("Step f1: Data Analyst SQL") if mem_monitor else nullcontext()):
            sql_run1 = client.post(
                f"/agents/{data_agent['id']}/run",
                headers=user_headers,
                json={"question": "List students with marks above 80"},
            )
        assert sql_run1.status_code == 200, f"Run call failed: {sql_run1.text}"
        r1_data = sql_run1.json()
        assert r1_data["status"] == "paused_for_approval", f"Expected paused_for_approval, got {r1_data['status']}"
        approval_id = r1_data["approval_id"]
        run_id1 = r1_data["run_id"]
        print(f"  Run #{run_id1} successfully paused for approval (Approval #{approval_id})")

        # Admin approves
        with (mem_monitor.track_chat("Step f1: Data Analyst Resume") if mem_monitor else nullcontext()):
            decide_res = client.post(
                f"/approvals/{approval_id}/decide",
                headers=admin_headers,
                json={"decision": "approve"},
            )
        assert decide_res.status_code == 200, f"Approval decision failed: {decide_res.text}"
        decide_data = decide_res.json()
        assert decide_data["decision"] == "approved"
        resumed_res = decide_data["run_result"]
        final_answer = resumed_res.get("answer", "")
        print(f"  Approved Final Answer:\n{final_answer}")
        print_trace_and_retries(run_id1)
        assert resumed_res["status"] == "completed"

        print("  -> PASS: High-risk approval workflow successfully paused, approved, and executed.")
        results["step_f1_approve"] = True
    except Exception as e:
        print(f"  -> FAIL (Approve path): {e}")
        results["step_f1_approve"] = False

    print("\n--- [Step f2] Data Analyst: 'List students with marks above 80' (Denial path) ---")
    try:
        with (mem_monitor.track_chat("Step f2: Data Analyst Deny Run") if mem_monitor else nullcontext()):
            sql_run2 = client.post(
                f"/agents/{data_agent['id']}/run",
                headers=user_headers,
                json={"question": "List students with marks above 80"},
            )
        assert sql_run2.status_code == 200, f"Run call failed: {sql_run2.text}"
        r2_data = sql_run2.json()
        assert r2_data["status"] == "paused_for_approval", f"Expected paused_for_approval, got {r2_data['status']}"
        deny_approval_id = r2_data["approval_id"]
        run_id2 = r2_data["run_id"]
        print(f"  Run #{run_id2} paused for approval (Approval #{deny_approval_id})")

        # Admin denies
        with (mem_monitor.track_chat("Step f2: Data Analyst Deny Decide") if mem_monitor else nullcontext()):
            deny_decide_res = client.post(
                f"/approvals/{deny_approval_id}/decide",
                headers=admin_headers,
                json={"decision": "deny"},
            )
        assert deny_decide_res.status_code == 200, f"Denial decision failed: {deny_decide_res.text}"
        deny_data = deny_decide_res.json()
        assert deny_data["decision"] == "denied"
        deny_run_res = deny_data["run_result"]
        deny_final_answer = deny_run_res.get("answer", "")
        print(f"  Denied Final Answer:\n{deny_final_answer}")
        print_trace_and_retries(run_id2)

        print("  -> PASS: Denial path cleanly handled without crashing the agent loop.")
        results["step_f2_deny"] = True
    except Exception as e:
        print(f"  -> FAIL (Denial path): {e}")
        results["step_f2_deny"] = False

    # --------------------------------------------------------------------------
    # Step g) Ask something not in the documents
    # --------------------------------------------------------------------------
    print("\n--- [Step g] Ask unanswerable question ---")
    try:
        unknown_q = "What is the average July rainfall in the Amazon rainforest?"
        with (mem_monitor.track_chat("Step g: Negative Retrieval") if mem_monitor else nullcontext()):
            unknown_res = client.post(
                f"/agents/{doc_agent['id']}/run",
                headers=user_headers,
                json={"question": unknown_q},
            )
        assert unknown_res.status_code == 200, f"Run call failed: {unknown_res.text}"
        un_data = unknown_res.json()
        un_ans = un_data.get("answer", "")
        run_id = un_data["run_id"]
        print(f"  Answer: {un_ans}")
        print_trace_and_retries(run_id)

        ans_lower = un_ans.lower()
        says_dont_know = any(k in ans_lower for k in [
            "do not know", "don't know", "not mention", "no information", "cannot find",
            "not found", "not provided", "does not contain", "no relevant", "unable to find",
            "not have enough information", "not enough information", "do not have"
        ])
        print(f"  Model recognized missing information: {says_dont_know}")
        assert says_dont_know, f"Expected agent to report it does not know, got: '{un_ans}'"

        print("  -> PASS: Agent correctly acknowledged missing context.")
        results["step_g_unknown"] = True
    except Exception as e:
        print(f"  -> FAIL: {e}")
        results["step_g_unknown"] = False

    return results


def main():
    print("=" * 70)
    print("  SOVEREIGN BENCHMARK: LIVE ACCEPTANCE VERIFIER & MEMORY PROFILER")
    print("=" * 70)

    # 1. Start or attach to backend
    running, proc = ensure_backend_running()
    if not running:
        sys.exit(1)

    # 2. Start psutil memory monitor
    backend_pid = proc.pid if proc else None
    mem_monitor = MemoryMonitor(backend_pid=backend_pid)
    mem_monitor.start()

    # 3. Iteration count: default 1 if run as 'live_check.py once', or specify e.g. 3
    num_iterations = 1
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        num_iterations = int(sys.argv[1])
    elif "--three" in sys.argv:
        num_iterations = 3

    all_runs_results: List[Dict[str, bool]] = []

    try:
        for i in range(1, num_iterations + 1):
            res = run_live_check_iteration(i, mem_monitor=mem_monitor)
            all_runs_results.append(res)
            time.sleep(1.0)
    finally:
        mem_monitor.stop()
        if proc:
            print("[CLEANUP] Stopping spawned backend server...")
            proc.terminate()

    # 4. Report statistics and memory profile (STEP 9)
    print("\n" + "=" * 70)
    print(f"  {num_iterations}-RUN LIVE ACCEPTANCE SUMMARY")
    print("=" * 70)

    all_keys = [
        ("step_a_health", "a) GET /health (Ollama & models present)"),
        ("step_b_auth", "b) Auth roles (1st=admin, 2nd=user)"),
        ("step_c_upload", "c) Document upload (attendance rules)"),
        ("step_d_doc_assistant", "d) Document Assistant (citation check)"),
        ("step_e_calculator", "e) Calculator tool used (15% of 2480)"),
        ("step_f1_approve", "f1) Data Analyst approval (approved)"),
        ("step_f2_deny", "f2) Data Analyst approval (denied)"),
        ("step_g_unknown", "g) Negative retrieval (says does not know)"),
    ]

    for key, desc in all_keys:
        successes = sum(1 for r in all_runs_results if r.get(key, False))
        rate = f"{successes}/{num_iterations} ({int(successes/num_iterations*100)}%)"
        status_sym = "[PASS]" if successes == num_iterations else "[FAIL]"
        print(f"  {status_sym} {desc:<50}: {rate}")

    # Memory Profile (STEP 9)
    print("\n" + "=" * 70)
    print("  RESOURCE USAGE & MEMORY BUDGET (psutil)")
    print("=" * 70)
    print(f"  Peak Ollama Process RAM (Sum across all Ollama/runner procs): {mem_monitor.peak_ollama_mb:.2f} MB")
    if mem_monitor.peak_ollama_breakdown:
        print("    - Per-process footprint at peak:")
        for name, pid, rss in mem_monitor.peak_ollama_breakdown:
            print(f"      * {name} (PID {pid}): {rss:.2f} MB")
    print(f"  Peak Backend Process RAM:                                     {mem_monitor.peak_backend_mb:.2f} MB")
    print(f"  Configured OLLAMA_NUM_CTX: {settings.OLLAMA_NUM_CTX} (<= 4096: {settings.OLLAMA_NUM_CTX <= 4096})")
    print(f"  Configured RAG_TOP_K:      {settings.RAG_TOP_K} (<= 3: {settings.RAG_TOP_K <= 3})")

    all_passed = all(
        all(r.get(k, False) for k, _ in all_keys) for r in all_runs_results
    )

    if all_passed:
        print(f"\n>>> ALL {num_iterations} RUN(S) PASSED 100% AGAINST REAL HOST OLLAMA (WORKING) <<<\n")
        sys.exit(0)
    else:
        print("\n>>> ONE OR MORE STEPS ENCOUNTERED FAILURES <<<\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
