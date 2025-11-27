from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator

# SQLite file lives at backend/data.db (relative path from backend/)
DATABASE_URL = "sqlite:///./data.db"

# Needed for SQLite with SQLAlchemy in multithreaded FastAPI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

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
