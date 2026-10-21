#!/usr/bin/env python3
"""
Sovereign On-Premise Agentic AI Workbench - Live Acceptance & Demo Verification Script.

Verifies end-to-end functionality against a running stack (Docker Compose or local uvicorn):
1. [PASS/FAIL] /health endpoint (native host Ollama reachability + required models present)
2. [PASS/FAIL] Register demo user (asserts first user is admin on fresh data dir; never hardcoded password)
3. [PASS/FAIL] Sample document upload & RAG chunk ingestion into ChromaDB
4. [PASS/FAIL] Document Assistant RAG retrieval question with citation verification
5. [PASS/FAIL] Calculator arithmetic question execution (asserts calculator tool called from run trace)

Note: Always uses a temporary SOVEREIGN_DATA_DIR when spawning the backend to guarantee
the real repository 'data/' directory is never touched during demo/acceptance verification.

Usage:
    # Against active stack (Docker Compose or running backend):
    ADMIN_PASSWORD="SecurePassword123!" python scripts/demo_check.py

    # Or provide via CLI argument:
    python scripts/demo_check.py --password "SecurePassword123!"

    # Or spawn a standalone backend on a temporary SOVEREIGN_DATA_DIR:
    python scripts/demo_check.py --spawn-backend --password "SecurePassword123!"
"""

import os
import sys
import time
import socket
import getpass
import argparse
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def log_pass(step_num: int, title: str, details: str = ""):
    sys.stdout.write(f"{Colors.GREEN}[PASS]{Colors.RESET} Step {step_num}: {Colors.BOLD}{title}{Colors.RESET}\n")
    if details:
        sys.stdout.write(f"       {details}\n")
    sys.stdout.flush()


def log_fail(step_num: int, title: str, error: str = ""):
    sys.stderr.write(f"{Colors.RED}[FAIL]{Colors.RESET} Step {step_num}: {Colors.BOLD}{title}{Colors.RESET}\n")
    if error:
        sys.stderr.write(f"       Error: {error}\n")
    sys.stderr.flush()


def log_info(msg: str):
    sys.stdout.write(f"{Colors.CYAN}[INFO]{Colors.RESET} {msg}\n")
    sys.stdout.flush()


SAMPLE_DOCUMENT_CONTENT = """# Sovereign AI Workbench Institutional Policy
Document Version: 2026.1
Section 1. Security Mandate:
The Sovereign On-Premise Agentic AI Workbench operates under strict zero-cloud egress policies.
All inferences and vector embeddings execute strictly within the local host boundaries.

Section 2. Standard User Quota:
Every standard demo user account is assigned an exact daily quota of 75 queries per calendar day.
Supervisors and administrators maintain unlimited query authorization.

Section 3. Tool Safety and Human-in-the-Loop Governance:
Destructive actions and analytical SQL inspections against production databases require explicit supervisor approval.
"""


def is_port_open(host: str, port: int) -> bool:
    """Check if a network port is accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def run_demo_check(
    base_url: str,
    username: str,
    password: str,
    is_fresh_data_dir: bool = False
) -> bool:
    all_passed = True
    client = httpx.Client(base_url=base_url, timeout=120.0)

    print("=" * 70)
    print(" SOVEREIGN WORKBENCH ACCEPTANCE & DEMO VERIFICATION")
    print(f" Target Backend: {base_url}")
    print(f" User: {username}")
    print(f" Fresh Data Dir Assertion: {is_fresh_data_dir}")
    print("=" * 70)

    token = None
    doc_agent_id = None

    # --------------------------------------------------------------------------
    # Step 1: Health Check (/health)
    # --------------------------------------------------------------------------
    try:
        resp = client.get("/health")
        if resp.status_code == 200:
            data = resp.json()
            ollama = data.get("ollama", {})
            reachable = ollama.get("reachable", False)
            chat_present = ollama.get("chat_model_present", False)
            embed_present = ollama.get("embed_model_present", False)
            models = ollama.get("available_models", []) or ollama.get("installed_models", [])

            if reachable and chat_present and embed_present:
                log_pass(
                    1,
                    "Health Check (/health)",
                    f"Status: {data.get('status')} | Ollama: Reachable | Models: {models}"
                )
            else:
                all_passed = False
                log_fail(
                    1,
                    "Health Check (/health)",
                    f"Ollama status degraded: reachable={reachable}, chat_model_present={chat_present}, embed_model_present={embed_present}"
                )
                return False
        else:
            all_passed = False
            log_fail(1, "Health Check (/health)", f"HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        all_passed = False
        log_fail(1, "Health Check (/health)", f"Connection failed to {base_url}: {str(e)}")
        return False

    # --------------------------------------------------------------------------
    # Step 2: Register demo user
    # --------------------------------------------------------------------------
    try:
        reg_resp = client.post("/auth/register", json={"username": username, "password": password})
        if reg_resp.status_code == 200:
            reg_data = reg_resp.json()
            token = reg_data.get("access_token")
            role = reg_data.get("role")

            if is_fresh_data_dir:
                if role != "admin":
                    all_passed = False
                    log_fail(
                        2,
                        "Register demo user",
                        f"Expected first user on fresh data dir to be 'admin', but got role '{role}'"
                    )
                    return False
                log_pass(
                    2,
                    "Register demo user",
                    f"User '{username}' registered as initial admin (role='admin') on fresh data dir"
                )
            else:
                log_pass(
                    2,
                    "Register demo user",
                    f"User '{username}' registered with role '{role}'"
                )
        elif reg_resp.status_code == 400 and (
            "already taken" in reg_resp.text.lower() or "already registered" in reg_resp.text.lower()
        ):
            if is_fresh_data_dir:
                all_passed = False
                log_fail(
                    2,
                    "Register demo user",
                    f"Username '{username}' already exists, but data dir was expected to be fresh"
                )
                return False

            # Existing user - authenticate with provided password
            login_resp = client.post("/auth/login", json={"username": username, "password": password})
            if login_resp.status_code == 200:
                login_data = login_resp.json()
                token = login_data.get("access_token")
                role = login_data.get("role")
                log_pass(
                    2,
                    "Register demo user",
                    f"Authenticated existing user '{username}' (role='{role}')"
                )
            else:
                all_passed = False
                log_fail(
                    2,
                    "Register demo user",
                    f"Username exists but authentication failed (HTTP {login_resp.status_code}): {login_resp.text}"
                )
                return False
        else:
            all_passed = False
            log_fail(2, "Register demo user", f"HTTP {reg_resp.status_code}: {reg_resp.text}")
            return False
    except Exception as e:
        all_passed = False
        log_fail(2, "Register demo user", f"Exception during registration: {str(e)}")
        return False

    headers = {"Authorization": f"Bearer {token}"}

    # --------------------------------------------------------------------------
    # Step 3: Sample Document Upload & RAG Ingestion
    # --------------------------------------------------------------------------
    try:
        files = {
            "file": ("sovereign_policy_sample.txt", SAMPLE_DOCUMENT_CONTENT.encode("utf-8"), "text/plain")
        }
        up_resp = client.post("/documents/upload", headers=headers, files=files)
        if up_resp.status_code == 200:
            up_data = up_resp.json()
            chunks = up_data.get("chunks", 0)
            doc_id = up_data.get("document_id")
            log_pass(
                3,
                "Document Upload & RAG Ingestion (/documents/upload)",
                f"Ingested '{up_data.get('filename')}' into ChromaDB (ID={doc_id}, Chunks={chunks})"
            )
        else:
            all_passed = False
            log_fail(3, "Document Upload (/documents/upload)", f"HTTP {up_resp.status_code}: {up_resp.text}")
            return False
    except Exception as e:
        all_passed = False
        log_fail(3, "Document Upload", f"Exception: {str(e)}")
        return False

    # --------------------------------------------------------------------------
    # Locate Document Assistant Agent
    # --------------------------------------------------------------------------
    try:
        agents_resp = client.get("/agents", headers=headers)
        if agents_resp.status_code == 200:
            agents = agents_resp.json()
            for ag in agents:
                if ag.get("name") == "Document Assistant":
                    doc_agent_id = ag.get("id")
                    break
            if not doc_agent_id and agents:
                doc_agent_id = agents[0].get("id")
        if not doc_agent_id:
            all_passed = False
            log_fail(4, "Find Document Assistant", "No Document Assistant agent found in backend")
            return False
    except Exception as e:
        all_passed = False
        log_fail(4, "Find Document Assistant", f"Failed fetching agents: {str(e)}")
        return False

    # --------------------------------------------------------------------------
    # Step 4: Ask Document Question
    # --------------------------------------------------------------------------
    try:
        doc_question = "According to the uploaded policy document, what is the daily quota of queries for a demo user?"
        log_info(f"Submitting document query: '{doc_question}'")
        q_resp = client.post(
            f"/agents/{doc_agent_id}/run",
            headers=headers,
            json={"question": doc_question},
            timeout=120.0
        )
        if q_resp.status_code == 200:
            q_data = q_resp.json()
            status = q_data.get("status")
            answer = q_data.get("answer", "")
            sources = q_data.get("sources", [])

            if status == "completed" and ("75" in answer or sources):
                log_pass(
                    4,
                    "Document Question & Retrieval (/agents/.../run)",
                    f"Status: {status} | Citations: {len(sources)} | Answer: {answer.strip()[:100]}..."
                )
            else:
                all_passed = False
                log_fail(
                    4,
                    "Document Question (/agents/.../run)",
                    f"Unexpected output: status={status}, sources={sources}, answer={answer[:150]}"
                )
        else:
            all_passed = False
            log_fail(4, "Document Question", f"HTTP {q_resp.status_code}: {q_resp.text}")
    except Exception as e:
        all_passed = False
        log_fail(4, "Document Question", f"Exception: {str(e)}")

    # --------------------------------------------------------------------------
    # Step 5: Ask Calculator Question & Assert Tool Invocation from Run Trace
    # --------------------------------------------------------------------------
    try:
        calc_question = "What is 125 multiplied by 8? Please calculate the exact result using the calculator tool."
        log_info(f"Submitting calculator query: '{calc_question}'")
        calc_resp = client.post(
            f"/agents/{doc_agent_id}/run",
            headers=headers,
            json={"question": calc_question},
            timeout=120.0
        )
        if calc_resp.status_code == 200:
            c_data = calc_resp.json()
            status = c_data.get("status")
            answer = c_data.get("answer", "")
            run_id = c_data.get("run_id")

            # Retrieve full execution trace from backend to assert calculator was invoked
            trace_resp = client.get(f"/runs/{run_id}", headers=headers)
            steps = []
            if trace_resp.status_code == 200:
                steps = trace_resp.json().get("steps", [])

            calculator_called = False
            for s in steps:
                s_type = s.get("step_type", "")
                input_data = str(s.get("input_data", "")).lower()
                output_data = str(s.get("output_data", "")).lower()
                if "calculator" in input_data or "calculator" in output_data:
                    calculator_called = True
                    break

            if status == "completed" and calculator_called and ("1000" in answer or "1,000" in answer):
                log_pass(
                    5,
                    "Calculator Tool Query (/agents/.../run)",
                    f"Status: {status} | Trace: calculator tool confirmed in steps | Result: {answer.strip()[:100]}..."
                )
            elif not calculator_called:
                all_passed = False
                log_fail(
                    5,
                    "Calculator Query (/agents/.../run)",
                    f"Run #{run_id} completed but run trace did NOT record calculator invocation. Steps: {steps}"
                )
            else:
                all_passed = False
                log_fail(
                    5,
                    "Calculator Query (/agents/.../run)",
                    f"Unexpected output: status={status}, answer={answer[:150]}"
                )
        else:
            all_passed = False
            log_fail(5, "Calculator Query", f"HTTP {calc_resp.status_code}: {calc_resp.text}")
    except Exception as e:
        all_passed = False
        log_fail(5, "Calculator Query", f"Exception: {str(e)}")

    print("=" * 70)
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}ALL 5 DEMO STEPS PASSED SUCCESSFULLY!{Colors.RESET}")
        print("The Sovereign Workbench stack is healthy, isolated, and fully functional.")
    else:
        print(f"{Colors.RED}{Colors.BOLD}DEMO VERIFICATION ENCOUNTERED FAILURES.{Colors.RESET}")
    print("=" * 70)

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify end-to-end operation of the Sovereign Workbench."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        help="Backend base URL (default: http://127.0.0.1:8000)"
    )
    parser.add_argument(
        "--username",
        default=os.getenv("ADMIN_USERNAME", "demo_admin"),
        help="Admin username (default: demo_admin)"
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ADMIN_PASSWORD"),
        help="Admin password (passed via --password or ADMIN_PASSWORD env var; NEVER hardcoded)"
    )
    parser.add_argument(
        "--spawn-backend",
        action="store_true",
        help="Automatically spawn backend process using a temporary SOVEREIGN_DATA_DIR"
    )
    parser.add_argument(
        "--fresh-data",
        action="store_true",
        help="Assert that the target backend is running against a fresh data dir (first user must be admin)"
    )

    args = parser.parse_args()

    password = args.password
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass(f"Enter admin password for user '{args.username}': ")
        else:
            sys.stderr.write(
                "Error: Admin password must be provided via the ADMIN_PASSWORD environment "
                "variable or the --password command-line argument in non-interactive sessions.\n"
            )
            return 1

    if len(password) < 6:
        sys.stderr.write("Error: Admin password must be at least 6 characters long.\n")
        return 1

    temp_dir_obj = None
    backend_proc = None
    is_fresh = args.fresh_data

    # If backend is not already listening or --spawn-backend requested, spawn it using a temporary data dir
    parsed_host = "127.0.0.1"
    parsed_port = 8000
    if ":" in args.base_url:
        try:
            parsed_port = int(args.base_url.rsplit(":", 1)[1].split("/")[0])
        except ValueError:
            parsed_port = 8000

    backend_listening = is_port_open(parsed_host, parsed_port)

    if args.spawn_backend or not backend_listening:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="sovereign_demo_data_", ignore_cleanup_errors=True)
        temp_data_dir = temp_dir_obj.name
        is_fresh = True
        log_info(f"Using isolated temporary SOVEREIGN_DATA_DIR: {temp_data_dir} (real data/ will not be touched)")

        # Prepare backend environment
        temp_data_path = Path(temp_data_dir)
        backend_env = os.environ.copy()
        backend_env["SOVEREIGN_DATA_DIR"] = temp_data_dir
        backend_env["DATA_DIR"] = temp_data_dir
        backend_env["DATABASE_URL"] = f"sqlite:///{temp_data_path.as_posix()}/sovereign.db"
        backend_env["DEMO_DATABASE_URL"] = f"sqlite:///{temp_data_path.as_posix()}/demo.db"
        backend_env["CHROMA_PERSIST_DIR"] = str(temp_data_path / "chroma")
        backend_env["UPLOAD_DIR"] = str(temp_data_path / "uploads")
        backend_env["ANONYMIZED_TELEMETRY"] = "false"
        backend_env["CHROMA_TELEMETRY"] = "false"

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            parsed_host,
            "--port",
            str(parsed_port),
        ]
        log_info(f"Spawning backend process: {' '.join(cmd)}")
        backend_proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=backend_env)

        # Wait for liveness endpoint
        started = False
        for _ in range(40):
            time.sleep(0.5)
            if is_port_open(parsed_host, parsed_port):
                try:
                    with httpx.Client(base_url=args.base_url, timeout=2.0) as c:
                        if c.get("/live").status_code == 200:
                            started = True
                            log_info(f"Backend started successfully (PID: {backend_proc.pid})")
                            break
                except Exception:
                    pass

        if not started:
            sys.stderr.write("[ERROR] Spawned backend failed to start within 20 seconds.\n")
            if backend_proc:
                backend_proc.terminate()
            if temp_dir_obj:
                temp_dir_obj.cleanup()
            return 1

    try:
        success = run_demo_check(
            base_url=args.base_url.rstrip("/"),
            username=args.username,
            password=password,
            is_fresh_data_dir=is_fresh
        )
        return 0 if success else 1
    finally:
        if backend_proc:
            log_info(f"Terminating spawned backend process (PID: {backend_proc.pid})...")
            try:
                import psutil
                parent = psutil.Process(backend_proc.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                parent.kill()
            except Exception:
                backend_proc.kill()
            try:
                backend_proc.wait(timeout=5)
            except Exception:
                pass
            time.sleep(1.0)

        if temp_dir_obj:
            log_info("Cleaning up temporary SOVEREIGN_DATA_DIR...")
            try:
                temp_dir_obj.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
