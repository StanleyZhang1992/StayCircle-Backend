from sqlalchemy import Column, Integer, String, ForeignKey, Date, DateTime, Index, func
from sqlalchemy.orm import declarative_mixin

from .db import Base


@declarative_mixin
class TimestampMixin:
    # UTC-aware timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


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


class Booking(Base, TimestampMixin):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    guest_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="reserved")
    # incremented on each update to support optimistic concurrency if/when used
    version = Column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_bookings_property_start", "property_id", "start_date"),
        Index("ix_bookings_property_end", "property_id", "end_date"),
    )
