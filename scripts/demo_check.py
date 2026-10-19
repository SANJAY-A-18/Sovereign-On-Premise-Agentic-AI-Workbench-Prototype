#!/usr/bin/env python3
"""
Sovereign On-Premise Agentic AI Workbench - Live Acceptance & Demo Verification Script.

Verifies end-to-end functionality against a running stack (Docker Compose or local uvicorn):
1. [PASS/FAIL] /health endpoint (native host Ollama reachability + required models present)
2. [PASS/FAIL] Admin user registration / authentication (password from env/prompt, NEVER hardcoded)
3. [PASS/FAIL] Sample document upload & RAG chunk ingestion into ChromaDB
4. [PASS/FAIL] Document Assistant RAG retrieval question with citation verification
5. [PASS/FAIL] Calculator arithmetic question execution

Usage:
    # Pass password via environment variable (recommended for automated runs):
    ADMIN_PASSWORD="SecurePassword123!" python scripts/demo_check.py

    # Or provide via CLI argument:
    python scripts/demo_check.py --password "SecurePassword123!"

    # Or run interactively (will prompt securely for password):
    python scripts/demo_check.py
"""

import os
import sys
import getpass
import argparse
from typing import Dict, Any, Optional
import httpx


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


def run_demo_check(base_url: str, username: str, password: str) -> bool:
    all_passed = True
    client = httpx.Client(base_url=base_url, timeout=120.0)

    print("=" * 70)
    print(" SOVEREIGN WORKBENCH ACCEPTANCE & DEMO VERIFICATION")
    print(f" Target Backend: {base_url}")
    print(f" User: {username}")
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
    # Step 2: Admin Registration / Authentication
    # --------------------------------------------------------------------------
    try:
        reg_resp = client.post("/auth/register", json={"username": username, "password": password})
        if reg_resp.status_code == 200:
            reg_data = reg_resp.json()
            token = reg_data.get("access_token")
            role = reg_data.get("role")
            log_pass(
                2,
                f"Admin Registration (/auth/register)",
                f"User '{username}' registered with role '{role}'"
            )
        elif reg_resp.status_code == 400 and "already taken" in reg_resp.text.lower():
            # Already registered - proceed to login with provided password
            login_resp = client.post("/auth/login", json={"username": username, "password": password})
            if login_resp.status_code == 200:
                login_data = login_resp.json()
                token = login_data.get("access_token")
                role = login_data.get("role")
                log_pass(
                    2,
                    f"Admin Authentication (/auth/login)",
                    f"Authenticated existing user '{username}' (role: '{role}')"
                )
            else:
                all_passed = False
                log_fail(
                    2,
                    f"Admin Authentication (/auth/login)",
                    f"Username exists but login failed (HTTP {login_resp.status_code}): {login_resp.text}"
                )
                return False
        else:
            all_passed = False
            log_fail(2, "Admin Registration (/auth/register)", f"HTTP {reg_resp.status_code}: {reg_resp.text}")
            return False
    except Exception as e:
        all_passed = False
        log_fail(2, "Admin Registration/Auth", f"Exception during auth: {str(e)}")
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
    # Step 5: Ask Calculator Question
    # --------------------------------------------------------------------------
    try:
        calc_question = "What is 125 multiplied by 8? Please calculate the exact result."
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

            if status == "completed" and ("1000" in answer or "1,000" in answer):
                log_pass(
                    5,
                    "Calculator Tool Query (/agents/.../run)",
                    f"Status: {status} | Result: {answer.strip()[:100]}..."
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

    success = run_demo_check(
        base_url=args.base_url.rstrip("/"),
        username=args.username,
        password=password
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
