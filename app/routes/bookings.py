from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas
from ..locks import redis_try_lock
from ..rate_limit import rate_limit
from .auth import get_current_user, require_tenant

router = APIRouter()


def _validate_dates(start_date: date, end_date: date) -> None:
    if start_date >= end_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_date must be before end_date")


def _has_overlap(db: Session, property_id: int, start_date: date, end_date: date) -> bool:
    """
    Overlap if NOT (existing.end_date <= start_date OR existing.start_date >= end_date)
    Only consider status='reserved'
    """
    exists = (
        db.query(models.Booking.id)
        .filter(
            models.Booking.property_id == property_id,
            models.Booking.status == "reserved",
            ~(
                (models.Booking.end_date <= start_date)
                | (models.Booking.start_date >= end_date)
            ),
        )
        .first()
    )
    return exists is not None


@router.post(
    "/bookings",
    response_model=schemas.BookingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("write"))],
)
def create_booking(
    payload: schemas.BookingCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_tenant),
) -> models.Booking:
    # Validate input
    _validate_dates(payload.start_date, payload.end_date)

    # Ensure property exists
    prop = db.get(models.Property, payload.property_id)
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    # Coarse per-property lock to reduce races across processes
    lock_key = f"lock:booking:property:{payload.property_id}"
    with redis_try_lock(lock_key, ttl_ms=5000) as locked:
        if not locked:
            # Another process is currently booking this property; ask client to retry shortly
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "busy", "retry_after": 1},
            )

        # Transactional overlap check + insert
        try:
            # Attempt to lock the property row for the duration (where supported)
            try:
                if str(db.bind.dialect.name) != "sqlite":
                    db.query(models.Property).filter(models.Property.id == payload.property_id).with_for_update(nowait=False).first()
            except Exception:
                # Some dialects/drivers may not support FOR UPDATE; proceed without row lock.
                pass

            if _has_overlap(db, payload.property_id, payload.start_date, payload.end_date):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dates overlap with an existing booking")

            obj = models.Booking(
                property_id=payload.property_id,
                guest_id=user.id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                status="reserved",
                version=1,
            )
            db.add(obj)
            db.commit()
            db.refresh(obj)
            return obj
        except HTTPException:
            # Bubble up API errors after rolling back if needed
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create booking: {exc}")


@router.get("/bookings/me", response_model=List[schemas.BookingRead])
def list_my_bookings(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> List[models.Booking]:
    if user.role == "tenant":
        q = (
            db.query(models.Booking)
            .filter(models.Booking.guest_id == user.id)
        )
    else:
        # Landlord: bookings on properties they own
        q = (
            db.query(models.Booking)
            .join(models.Property, models.Property.id == models.Booking.property_id)
            .filter(models.Property.owner_id == user.id)
        )

    items = (
        q.order_by(models.Booking.start_date.desc(), models.Booking.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return items


@router.delete(
    "/bookings/{booking_id}",
    response_model=schemas.BookingRead,
    dependencies=[Depends(rate_limit("write"))],
)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Booking:
    obj = db.get(models.Booking, booking_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Authorization: tenant can cancel own booking; landlord can cancel if booking belongs to their property
    if user.role == "tenant":
        if obj.guest_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to cancel this booking")
    else:
        prop = db.get(models.Property, obj.property_id)
        if not prop or prop.owner_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to cancel this booking")

    # Idempotent cancel
    if obj.status != "cancelled":
        obj.status = "cancelled"
        obj.version = (obj.version or 1) + 1
        try:
            db.add(obj)
            db.commit()
            db.refresh(obj)
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to cancel booking: {exc}")

    return obj
