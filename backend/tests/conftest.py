"""测试使用临时数据库，避免读写开发者的真实搜索与反馈记录。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.storage import db


@pytest.fixture(scope="session", autouse=True)
def isolated_database(tmp_path_factory):
    previous_engine, previous_sessions = db._engine, db._SessionLocal
    location = tmp_path_factory.mktemp("shopping-test") / "test.db"
    engine = create_engine(f"sqlite:///{location}", connect_args={"check_same_thread": False})
    db._engine = engine
    db._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db.init_db()
    try:
        yield
    finally:
        engine.dispose()
        db._engine, db._SessionLocal = previous_engine, previous_sessions
