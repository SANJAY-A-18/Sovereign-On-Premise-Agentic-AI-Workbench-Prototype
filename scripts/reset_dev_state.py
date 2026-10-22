#!/usr/bin/env python3
"""
Sovereign On-Premise Agentic AI Workbench - Development State Reset Tool.

Resets the development environment to a verified clean state:
1. Refuses to run if ports 8000 (Backend API) or 8501 (Streamlit UI) are in use (unless --force).
2. Prompts for user confirmation (unless --yes).
3. Backs up current data/ to a timestamped folder: data_backup_YYYYMMDD_HHMMSS (git-ignored).
4. Purges all application state:
   - Removes sovereign.db (and WAL/SHM files) -> users=0, documents=0, runs=0, steps=0, approvals=0, audit_logs=0.
   - Clears Chroma vector store -> vector embeddings=0.
   - Clears uploaded files (data/uploads/) and log files (data/logs/).
   - Recreates empty directories with .gitkeep.
5. Re-seeds data/demo.db with the canonical 10-row students table matching startup specifications.
   Verifies row counts and evaluation ground truths:
   - Total rows: 10
   - Students with GPA > 3.80: 4
   - Marks for Meera Nair: 89
6. NEVER touches .env, eval/, tests/, docs/, source code, or existing data_backup_* folders.

Usage:
    python scripts/reset_dev_state.py [--force] [--yes]
    ./scripts/reset_dev_state.ps1 [-Force] [-Yes]
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
from typing import Dict, Any, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def check_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a network port is currently open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except (socket.error, ConnectionRefusedError):
            return False


def verify_ground_truth(conn: sqlite3.Connection) -> Tuple[bool, str]:
    """Verify demo.db students table conforms to evaluation benchmark answers."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM students;")
    total_count = cursor.fetchone()[0]
    if total_count != 10:
        return False, f"Expected 10 student rows, found {total_count}"

    cursor.execute("SELECT COUNT(*) FROM students WHERE gpa > 3.80;")
    gpa_count = cursor.fetchone()[0]
    if gpa_count != 4:
        return False, f"Expected 4 students with GPA > 3.80, found {gpa_count}"

    cursor.execute("SELECT marks FROM students WHERE name = 'Meera Nair';")
    row = cursor.fetchone()
    if not row or row[0] != 89:
        return False, f"Expected Meera Nair marks == 89, found {row[0] if row else 'None'}"

    return True, f"Verified 10 rows (GPA > 3.80: {gpa_count}, Meera Nair marks: {row[0]})"


def reseed_demo_db(demo_db_path: Path):
    """Recreate and seed demo.db with the canonical students table."""
    # Remove existing demo.db and any WAL/SHM files
    for suffix in ("", "-wal", "-shm"):
        f = demo_db_path.parent / (demo_db_path.name + suffix)
        if f.exists():
            try:
                f.unlink()
            except Exception as e:
                print(f"[!] Warning removing {f.name}: {e}")

    conn = sqlite3.connect(demo_db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE students (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        marks INTEGER NOT NULL DEFAULT 85,
        gpa REAL NOT NULL,
        graduation_year INTEGER NOT NULL
    );
    """)

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

    ok, msg = verify_ground_truth(conn)
    conn.close()
    if not ok:
        raise RuntimeError(f"demo.db ground truth validation failed: {msg}")
    print(f"[+] Re-seeded {demo_db_path.name}: {msg}")


def inspect_counts() -> Dict[str, Any]:
    """Inspect current database counts across sovereign.db and demo.db."""
    counts = {
        "users": 0,
        "documents": 0,
        "runs": 0,
        "steps": 0,
        "approvals": 0,
        "audit_logs": 0,
        "vector_count": 0,
        "students": 0,
    }

    sov_db = DATA_DIR / "sovereign.db"
    if sov_db.exists():
        try:
            conn = sqlite3.connect(sov_db)
            c = conn.cursor()
            for tbl, key in [
                ("users", "users"),
                ("documents", "documents"),
                ("runs", "runs"),
                ("steps", "steps"),
                ("approvals", "approvals"),
                ("audit_logs", "audit_logs"),
            ]:
                try:
                    c.execute(f"SELECT COUNT(*) FROM {tbl};")
                    counts[key] = c.fetchone()[0]
                except sqlite3.OperationalError:
                    counts[key] = 0
            conn.close()
        except Exception as e:
            print(f"[!] Warning reading sovereign.db: {e}")

    demo_db = DATA_DIR / "demo.db"
    if demo_db.exists():
        try:
            conn = sqlite3.connect(demo_db)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM students;")
            counts["students"] = c.fetchone()[0]
            conn.close()
        except Exception:
            counts["students"] = 0

    chroma_dir = DATA_DIR / "chroma"
    if chroma_dir.exists():
        # Count indexed SQLite records in Chroma if chroma.sqlite3 exists
        chroma_sqlite = chroma_dir / "chroma.sqlite3"
        if chroma_sqlite.exists():
            try:
                conn = sqlite3.connect(chroma_sqlite)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM embeddings;")
                counts["vector_count"] = c.fetchone()[0]
                conn.close()
            except Exception:
                # If embeddings table doesn't exist, count files or 0
                counts["vector_count"] = 0
        else:
            counts["vector_count"] = 0

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Reset development state: purge users, documents, runs, approvals, audit logs, vector store, and reseed demo.db"
    )
    parser.add_argument("--force", action="store_true", help="Bypass port 8000/8501 check if services are running")
    parser.add_argument("--yes", "-y", action="store_true", help="Confirm reset without interactive prompt")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating data_backup_YYYYMMDD_HHMMSS backup directory")
    args = parser.parse_args()

    print("=" * 80)
    print(" Sovereign Workbench Development State Reset Tool")
    print("=" * 80)

    # 1. Port Check: refuse if ports 8000 or 8501 are listening (unless --force)
    active_ports = []
    for port, label in [(8000, "Backend API (uvicorn)"), (8501, "Streamlit Web UI")]:
        if check_port_in_use(port):
            active_ports.append((port, label))

    if active_ports:
        port_list = ", ".join([f"Port {p} ({lbl})" for p, lbl in active_ports])
        if not args.force:
            print(f"[-] Refusing to reset: Active process detected on {port_list}.")
            print("    Please terminate the running server/UI process before resetting state.")
            print("    (Pass --force to override this check if testing or managing externally.)")
            sys.exit(1)
        else:
            print(f"[!] Warning: Services currently active on {port_list}, continuing due to --force.")

    # 2. Confirmation Prompt (unless --yes)
    if not args.yes:
        try:
            confirm = input(
                "Are you sure you want to reset development state?\n"
                "This will purge all users, documents, runs, steps, approvals, audit logs, and vector embeddings.\n"
                "Enter 'y' or 'yes' to proceed: "
            ).strip().lower()
            if confirm not in ("y", "yes"):
                print("[-] Reset cancelled by user.")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print("\n[-] Reset cancelled.")
            sys.exit(0)

    # 3. Create timestamped backup of data/ (unless --no-backup)
    if not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = PROJECT_ROOT / f"data_backup_{timestamp}"

        if DATA_DIR.exists():
            try:
                shutil.copytree(DATA_DIR, backup_dir)
                print(f"[+] Successfully created backup: {backup_dir.name}")
            except Exception as e:
                print(f"[!] Warning: Backup creation encountered error: {e}")
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
    else:
        print("[*] Skipping backup creation (--no-backup specified)")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 4. Remove sovereign.db, Chroma vector store, uploads, and logs
    print("[*] Purging application state (users, documents, runs, steps, approvals, audit logs, vectors)...")

    # Sovereign DB and WAL/SHM
    for f in DATA_DIR.glob("sovereign.db*"):
        try:
            f.unlink()
            print(f"    - Removed {f.name}")
        except Exception as e:
            print(f"    [!] Error removing {f.name}: {e}")

    # Chroma vector store
    chroma_dir = DATA_DIR / "chroma"
    if chroma_dir.exists():
        try:
            shutil.rmtree(chroma_dir)
            print("    - Removed Chroma vector store directory")
        except Exception as e:
            print(f"    [!] Error removing Chroma dir: {e}")
    chroma_dir.mkdir(parents=True, exist_ok=True)

    # Uploads directory
    uploads_dir = DATA_DIR / "uploads"
    if uploads_dir.exists():
        try:
            shutil.rmtree(uploads_dir)
            print("    - Cleared uploads directory")
        except Exception as e:
            print(f"    [!] Error removing uploads dir: {e}")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Logs directory
    logs_dir = DATA_DIR / "logs"
    if logs_dir.exists():
        try:
            shutil.rmtree(logs_dir)
            print("    - Cleared logs directory")
        except Exception as e:
            print(f"    [!] Error removing logs dir: {e}")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Touch .gitkeep
    (DATA_DIR / ".gitkeep").touch(exist_ok=True)

    # 5. Re-seed data/demo.db with the canonical students table
    demo_db_path = DATA_DIR / "demo.db"
    reseed_demo_db(demo_db_path)

    # 6. Final verification of state counts
    counts = inspect_counts()

    print("\n" + "=" * 80)
    print(" STATE RESET VERIFICATION REPORT")
    print("=" * 80)
    print(f" Users:               {counts['users']}")
    print(f" Documents:           {counts['documents']}")
    print(f" Runs:                {counts['runs']}")
    print(f" Steps:               {counts['steps']}")
    print(f" Approvals:           {counts['approvals']}")
    print(f" Audit Logs:          {counts['audit_logs']}")
    print(f" Vector Count:        {counts['vector_count']}")
    print(f" Demo.db Students:    {counts['students']} (GPA>3.80: 4, Meera Nair Marks: 89)")

    clean = (
        counts["users"] == 0
        and counts["documents"] == 0
        and counts["runs"] == 0
        and counts["steps"] == 0
        and counts["approvals"] == 0
        and counts["audit_logs"] == 0
        and counts["vector_count"] == 0
        and counts["students"] == 10
    )

    if clean:
        print(" Status:              CLEAN & READY FOR OPERATION")
        print("=" * 80 + "\n")
        sys.exit(0)
    else:
        print(" Status:              INCOMPLETE RESET DETECTED")
        print("=" * 80 + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
