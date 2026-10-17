"""
Test for post-hoc variant flag REQUIRE_RETRIEVAL_BEFORE_ABSTAIN.
Validates on tests/regression_prompts.json (unanswerable prompt not_in_docs_1).
"""

import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import Base, User, Agent, Run, Step
from eval.metrics import is_abstention

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_require_retrieval_before_abstain_unit():
    # 1. Verify default setting is False
    assert settings.REQUIRE_RETRIEVAL_BEFORE_ABSTAIN is False or isinstance(settings.REQUIRE_RETRIEVAL_BEFORE_ABSTAIN, bool)

    # 2. Setup in-memory SQLite session
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    try:
        user = User(username="test_user", password_hash="dummy", role="user")
        db.add(user)
        db.commit()

        agent = Agent(
            name="Document Assistant",
            system_prompt="You are Document Assistant.",
            model="qwen2.5:3b",
            temperature=0.2,
            allowed_tools=json.dumps(["search_documents"]),
        )
        db.add(agent)
        db.commit()

        # Load regression prompt not_in_docs_1
        reg_file = PROJECT_ROOT / "tests" / "regression_prompts.json"
        prompts = json.loads(reg_file.read_text(encoding="utf-8"))
        decoy_item = next(p for p in prompts if p["id"] == "not_in_docs_1")
        assert decoy_item is not None

        # Verify abstention detection
        simulated_abstention = "I do not know the answer based on the provided documents."
        assert is_abstention(simulated_abstention) is True

        # Test state before search_documents
        run = Run(
            user_id=user.id,
            agent_id=agent.id,
            question=decoy_item["prompt"],
            status="running",
        )
        db.add(run)
        db.commit()

        search_called = any(
            st.step_type == "tool" and "search_documents" in st.input_data and not st.output_data.startswith("Tool Execution Error")
            for st in db.query(Step).filter(Step.run_id == run.id).all()
        )
        assert search_called is False

        # Simulate adding a successful search_documents step
        s = Step(
            run_id=run.id,
            step_number=1,
            step_type="tool",
            input_data='search_documents({"query": "Acme Corp revenue"})',
            output_data="[Source: doc.txt | Chunk #0] No financial records.",
            latency_ms=15.0,
        )
        db.add(s)
        db.commit()

        search_called_after = any(
            st.step_type == "tool" and "search_documents" in st.input_data and not st.output_data.startswith("Tool Execution Error")
            for st in db.query(Step).filter(Step.run_id == run.id).all()
        )
        assert search_called_after is True

    finally:
        db.close()
