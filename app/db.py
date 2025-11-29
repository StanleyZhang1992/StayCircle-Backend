from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator
import os

# SQLite file lives at backend/data.db (relative path from backend/)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")

# Create engine
# - SQLite: allow same-thread for dev convenience
# - MySQL/others: enable robust pooling to avoid stale connections
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=280,  # refresh connections periodically to avoid MySQL gone away
        pool_size=10,
        max_overflow=20,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator:
    """
    FastAPI dependency that yields a DB session and ensures it is closed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
