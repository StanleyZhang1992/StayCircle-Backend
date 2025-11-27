from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_mixin

from .db import Base


@declarative_mixin
class TimestampMixin:
    # Reserved for future sprints (created_at/updated_at). Kept minimal per Sprint 1 scope.
    pass


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, index=True)  # "landlord" or "tenant"


class Property(Base, TimestampMixin):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    price_cents = Column(Integer, nullable=False)
