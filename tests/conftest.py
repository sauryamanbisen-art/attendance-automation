"""Pytest shared test fixtures and configuration."""

from collections.abc import Generator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.adapters.fake.adapter import FakePortalAdapter
from app.database import get_db
from app.database.base import Base
from app.models.professor_mapping import ProfessorMapping
from app.models.subject import Subject
from main import app

# In-memory SQLite database dedicated to isolated tests
TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(name="db_session")
def fixture_db_session() -> Generator[Session, None, None]:
    """Create a pristine in-memory SQLite database session for a test."""
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = testing_session_local()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden database dependency."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(name="fake_adapter")
def fixture_fake_adapter() -> FakePortalAdapter:
    """Default FakePortalAdapter instance."""
    return FakePortalAdapter()


@pytest.fixture(name="sample_subject")
def fixture_sample_subject(db_session: Session) -> Subject:
    """Pre-populated subject with professor mapping in the test database."""
    subject = Subject(code="CS101", name="Python Programming")
    db_session.add(subject)
    db_session.flush()

    mapping = ProfessorMapping(
        subject_id=subject.id,
        professor_name="Dr. Alan Turing",
        professor_email="turing@university.edu",
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(subject)
    return subject
