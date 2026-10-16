"""
Pytest configuration and global test isolation fixtures.
Ensures tests NEVER touch the host ./data folder.
Applies environment overrides before any application modules are imported,
and provisions isolated temporary directories per test via pytest tmp_path.
"""

import os
import sys
import tempfile
from pathlib import Path
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ==============================================================================
# Pre-import Environment Isolation: Set before ANY backend modules are imported
# ==============================================================================
_BOOTSTRAP_DIR = Path(tempfile.mkdtemp(prefix="sovereign_boot_isolation_"))
_BOOT_DATA = _BOOTSTRAP_DIR / "data"
_BOOT_UPLOADS = _BOOT_DATA / "uploads"
_BOOT_CHROMA = _BOOT_DATA / "chroma"
_BOOT_SOVEREIGN_DB = _BOOT_DATA / "sovereign.db"
_BOOT_DEMO_DB = _BOOT_DATA / "demo.db"

_BOOT_UPLOADS.mkdir(parents=True, exist_ok=True)
_BOOT_CHROMA.mkdir(parents=True, exist_ok=True)

os.environ["DATA_DIR"] = str(_BOOT_DATA)
os.environ["SOVEREIGN_DATA_DIR"] = str(_BOOT_DATA)
os.environ["UPLOAD_DIR"] = str(_BOOT_UPLOADS)
os.environ["CHROMA_PERSIST_DIR"] = str(_BOOT_CHROMA)
os.environ["DATABASE_URL"] = f"sqlite:///{_BOOT_SOVEREIGN_DB}"
os.environ["DEMO_DATABASE_URL"] = f"sqlite:///{_BOOT_DEMO_DB}"

# Now safe to import backend modules
from backend.config import settings, EMBEDDING_DIM
import backend.config as config_mod
import backend.db as db_mod
import backend.rag as rag_mod
import backend.tools as tools_mod
import backend.main as main_mod


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """
    Guarantees strict per-test isolation using pytest tmp_path:
    - Temporary SQLite database (sovereign.db + demo.db)
    - Temporary Chroma persistence directory
    - Temporary uploads folder
    Zero modifications occur in ./data.
    """
    test_data = tmp_path / "data"
    test_uploads = test_data / "uploads"
    test_chroma = test_data / "chroma"
    test_sovereign_db = test_data / "sovereign.db"
    test_demo_db = test_data / "demo.db"

    test_uploads.mkdir(parents=True, exist_ok=True)
    test_chroma.mkdir(parents=True, exist_ok=True)

    # 1. Apply environment overrides for child processes and subprocesses
    monkeypatch.setenv("DATA_DIR", str(test_data))
    monkeypatch.setenv("SOVEREIGN_DATA_DIR", str(test_data))
    monkeypatch.setenv("UPLOAD_DIR", str(test_uploads))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(test_chroma))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_sovereign_db}")
    monkeypatch.setenv("DEMO_DATABASE_URL", f"sqlite:///{test_demo_db}")

    # 2. Update config module references
    config_mod.DATA_DIR = test_data
    config_mod.UPLOAD_DIR = test_uploads
    config_mod.CHROMA_DIR = test_chroma

    # 3. Update centralized settings instance
    settings.DATA_DIR = str(test_data)
    settings.UPLOAD_DIR = str(test_uploads)
    settings.CHROMA_PERSIST_DIR = str(test_chroma)
    settings.DATABASE_URL = f"sqlite:///{test_sovereign_db}"
    settings.DEMO_DATABASE_URL = f"sqlite:///{test_demo_db}"

    # 4. Rebind SQLite engine and session factory to test database
    db_mod.reset_db_engine()
    main_mod.SessionLocal = db_mod.SessionLocal
    db_mod.init_db()
    db_mod.init_demo_db()

    # 5. Point embedded Chroma vector store to test chroma directory
    test_vs = rag_mod.VectorStore(persist_dir=str(test_chroma))
    rag_mod.vector_store = test_vs
    tools_mod.vector_store = test_vs
    main_mod.vector_store = test_vs

    yield {
        "tmp_path": tmp_path,
        "data_dir": test_data,
        "uploads_dir": test_uploads,
        "chroma_dir": test_chroma,
        "sovereign_db": test_sovereign_db,
        "demo_db": test_demo_db,
        "embedding_dim": EMBEDDING_DIM,
    }

    # Teardown
    db_mod.engine.dispose()
