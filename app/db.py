from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator
import os

# SQLite file lives at backend/data.db (relative path from backend/)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")

# Create engine, handle SQLite thread check only when using SQLite
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

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
