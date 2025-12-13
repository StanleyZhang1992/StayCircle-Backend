from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .db import SessionLocal
from . import models


def sweep_expired_bookings(db: Optional[Session] = None) -> int:
    """
    Transition pending_payment bookings with expires_at in the past to cancelled_expired.

    Returns the number of rows updated.
    """
    created_session = False
    if db is None:
        db = SessionLocal()
        created_session = True

    try:
        now = datetime.now(timezone.utc)
        items = (
            db.query(models.Booking)
            .filter(
                models.Booking.status == "pending_payment",
                models.Booking.expires_at != None,  # noqa: E711
                models.Booking.expires_at < now,
            )
            .all()
        )
        for obj in items:
            # Idempotent guard
            # Normalize expires_at to timezone-aware UTC for safe comparison.
            exp = obj.expires_at
            if exp is not None and getattr(exp, "tzinfo", None) is None:
                # Some backends (e.g., SQLite) may return naive datetimes; treat stored values as UTC.
                exp = exp.replace(tzinfo=timezone.utc)
            if obj.status == "pending_payment" and exp and exp < now:
                obj.status = "cancelled_expired"
                if not obj.cancel_reason:
                    obj.cancel_reason = "expired"
                obj.version = (obj.version or 1) + 1
                db.add(obj)
        if items:
            db.commit()
        return len(items)
    except Exception:
        db.rollback()
        raise
    finally:
        if created_session:
            db.close()
