"""
Configuration module for the Sovereign On-Premise Agentic AI Workbench.
Reads settings from environment variables and provides centralized defaults.
Designed for offline execution on Windows (8 GB RAM budget).
"""

import os
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings


# Disable telemetry globally for offline operation
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_DATA_DIR = os.getenv("SOVEREIGN_DATA_DIR") or os.getenv("DATA_DIR")
DATA_DIR = Path(_ENV_DATA_DIR).resolve() if _ENV_DATA_DIR else (BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# Central constant for embedding dimensions (e.g. nomic-embed-text standard 768)
DEFAULT_EMBED_DIM = 768
EMBEDDING_DIM = 768


class Settings(BaseSettings):
    # Base data directory
    DATA_DIR: str = str(DATA_DIR)

    # Ollama Host Runtime
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text"
    OLLAMA_NUM_CTX: int = 4096
    OLLAMA_TIMEOUT_SECONDS: int = 120
    EMBED_DIM: int = EMBEDDING_DIM

    # Auth & Security
    JWT_SECRET_KEY: str = "sovereign-workbench-local-offline-secret-key-2026"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Database
    DATABASE_URL: str = f"sqlite:///{Path(DATA_DIR) / 'sovereign.db'}"
    DEMO_DATABASE_URL: str = f"sqlite:///{Path(DATA_DIR) / 'demo.db'}"

    # Chroma Vector Store & Uploads
    CHROMA_PERSIST_DIR: str = str(CHROMA_DIR)
    UPLOAD_DIR: str = str(UPLOAD_DIR)

    # Agent Loop Parameters
    ENABLE_RETRY: bool = True
    MAX_AGENT_ITERATIONS: int = 5
    OLLAMA_JSON_MODE: bool = True
    PROMPT_VARIANT: str = "hardened"  # "hardened" or "baseline"


    # RAG Chunker Configuration
    RAG_CHUNK_SIZE: int = 500
    RAG_CHUNK_OVERLAP: int = 50
    RAG_TOP_K: int = 3

    @field_validator("OLLAMA_JSON_MODE", mode="before")
    @classmethod
    def parse_json_mode(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)


    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
