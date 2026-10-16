"""
Unit tests for safe tool implementations.
Tests:
- Calculator (valid arithmetic and malicious code rejection)
- File reader (path traversal rejection)
- SQL reader (SELECT-only and mutation/injection rejection)
Runs completely offline without Ollama.
"""

from pathlib import Path
from backend.config import settings
from backend.db import init_demo_db
from backend.tools import calculator, read_file, read_sql


# ==============================================================================
# Calculator Tests
# ==============================================================================

def test_calculator_valid_arithmetic():
    assert calculator("2 + 2") == "4"
    assert calculator("(10 * 5) - (20 / 4)") == "45.0"
    assert calculator("2 ** 8") == "256"
    assert calculator("100 % 7") == "2"
    assert calculator("-15 + 30") == "15"
    assert calculator("3.5 * 2") == "7.0"


def test_calculator_division_by_zero():
    res = calculator("10 / 0")
    assert "Error" in res
    assert "zero" in res.lower()


def test_calculator_rejects_malicious_import():
    # Attempt Python code execution
    res1 = calculator("__import__('os').system('dir')")
    assert "Error" in res1
    assert "Dangerous or unsupported" in res1 or "Invalid" in res1

    res2 = calculator("open('secret.txt')")
    assert "Error" in res2

    res3 = calculator("eval('1+1')")
    assert "Error" in res3

    res4 = calculator("[x for x in range(10)]")
    assert "Error" in res4


# ==============================================================================
# File Reader Tests (Path Traversal Protection)
# ==============================================================================

def test_read_file_safe_access(tmp_path):
    # Create a safe test file inside uploads
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    test_file = upload_dir / "safe_test.txt"
    test_file.write_text("Hello Sovereign World!", encoding="utf-8")

    content = read_file("safe_test.txt")
    assert content == "Hello Sovereign World!"


def test_read_file_rejects_path_traversal():
    # Attempt parent directory traversal
    res1 = read_file("../config.py")
    assert "Security Error" in res1 or "Path traversal" in res1

    res2 = read_file("../../etc/passwd")
    assert "Security Error" in res2 or "Path traversal" in res2

    res3 = read_file(r"..\..\Windows\System32\cmd.exe")
    assert "Security Error" in res3 or "Path traversal" in res3

    # Absolute paths
    res4 = read_file("C:/Windows/System32/drivers/etc/hosts")
    assert "Security Error" in res4


# ==============================================================================
# Read SQL Tests (SELECT-only on demo.db)
# ==============================================================================

def test_read_sql_valid_select():
    init_demo_db()
    res = read_sql("SELECT name, department, gpa FROM students WHERE gpa >= 3.8")
    assert "name | department | gpa" in res
    assert "Aarav Sharma" in res or "Ananya Sen" in res


def test_read_sql_rejects_mutations():
    init_demo_db()

    # INSERT
    res_insert = read_sql("INSERT INTO students (id, name, department, gpa, graduation_year) VALUES (99, 'Hacker', 'CS', 4.0, 2025)")
    assert "Security Error" in res_insert

    # UPDATE
    res_update = read_sql("UPDATE students SET gpa = 4.0")
    assert "Security Error" in res_update

    # DELETE
    res_delete = read_sql("DELETE FROM students WHERE id = 1")
    assert "Security Error" in res_delete

    # DROP TABLE
    res_drop = read_sql("DROP TABLE students")
    assert "Security Error" in res_drop


def test_read_sql_rejects_multiple_statements():
    init_demo_db()
    res = read_sql("SELECT * FROM students; DROP TABLE students;")
    assert "Security Error" in res
    assert "Multiple SQL statements" in res
