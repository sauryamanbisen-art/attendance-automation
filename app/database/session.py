"""Database engine, session management, and lifecycle."""

import sqlite3
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.base import Base

settings = get_settings()

# Connect args specific to SQLite
connect_args: dict[str, Any] = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30.0

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: object, connection_record: object) -> None:
    """Enforce SQLite foreign key constraints, WAL journal mode, and busy timeout."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a database session and safely closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables and ensure schema is up to date."""
    # Ensure all models are registered with Base.metadata before creating
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Check if google_chat_space column exists in professor_mappings, add if missing
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(professor_mappings)"))
            columns = [row[1] for row in result.fetchall()]
            if columns and "google_chat_space" not in columns:
                conn.execute(text("ALTER TABLE professor_mappings ADD COLUMN google_chat_space VARCHAR(255)"))
                conn.commit()
            if columns and "is_active" not in columns:
                conn.execute(text("ALTER TABLE professor_mappings ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))
                conn.commit()
    except Exception:
        pass
