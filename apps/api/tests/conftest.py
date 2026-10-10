import os

import pytest

# 在导入数据库模块之前切换配置，测试不得触碰真实家庭数据库或调用收费模型。
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LLM_API_KEY"] = ""
os.environ["AITECHFLUX_API_KEY"] = ""
os.environ["BIGMODEL_API_KEY"] = ""

from app.db.seed import seed_demo_data


@pytest.fixture(autouse=True)
def _database_schema():
    """每个测试使用全新空库：发布/反馈等状态不能跨测试泄漏。"""
    from app.db import models  # noqa: F401
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _seed_demo_data():
    seed_demo_data()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """单测不打真实云端模型，始终走规则基线路径。"""
    from app.services import agent_service

    monkeypatch.setattr(agent_service, "build_llm_provider", lambda settings: None)
