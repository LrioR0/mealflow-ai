import pytest

from app.db.seed import seed_demo_data


@pytest.fixture(autouse=True)
def _database_schema():
    from app.db.session import create_database_schema

    create_database_schema()


@pytest.fixture(autouse=True)
def _seed_demo_data():
    seed_demo_data()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """单测不打真实云端模型，始终走规则基线路径。"""
    from app.services import agent_service

    monkeypatch.setattr(agent_service, "build_llm_provider", lambda settings: None)
