from __future__ import annotations

import os
from typing import Tuple, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from . import models, schemas
from .routes.auth import require_tenant

# Stripe SDK is optional at runtime (tests/CI may not provide keys)
try:
    import stripe  # type: ignore
except Exception:  # pragma: no cover
    stripe = None  # type: ignore

router = APIRouter()

# ENV
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()


def stripe_enabled() -> bool:
    """
    Returns True only if Stripe SDK is importable and STRIPE_SECRET_KEY is present.
    Tests/CI can run with this disabled to avoid network calls.
    """
    return bool(stripe and STRIPE_SECRET_KEY)


def _init_stripe() -> None:
    if not stripe_enabled():
        raise RuntimeError("Stripe not enabled (SDK missing or STRIPE_SECRET_KEY not set)")
    stripe.api_key = STRIPE_SECRET_KEY


def create_payment_intent(
    amount_cents: int,
    currency: str,
    booking_id: int,
    property_id: int,
    idempotency_key: str,
) -> Tuple[str, str]:
    """
    Create a Stripe PaymentIntent (test mode) and return (payment_intent_id, client_secret).
    If Stripe is disabled (e.g., tests), return deterministic fake values that look like real IDs.
    """
    if not stripe_enabled():
        # Local/test fallback: generate synthetic IDs and secrets (no network calls)
        fake_pi_id = f"pi_test_{booking_id}"
        fake_cs = f"test_client_secret_{booking_id}"
        return fake_pi_id, fake_cs

    _init_stripe()
    # Use automatic_payment_methods to keep UI simple with PaymentElement
    pi = stripe.PaymentIntent.create(
        amount=int(amount_cents),
        currency=currency.lower(),
        metadata={"booking_id": str(booking_id), "property_id": str(property_id)},
        automatic_payment_methods={"enabled": True},
        idempotency_key=idempotency_key,
    )
    # Ensure idempotency on the transport-layer via HTTP header
    # The python SDK uses 'idempotency_key' via request options
    # NOTE: Because we used a separate create() above, to strictly honor idempotency key,
    # callers should rely on SDK's idempotency. Here for simplicity we re-issue with same key if needed.
    # In practice, retries should pass the same idempotency_key for the same logical request.

    # Retrieve client secret
    client_secret: Optional[str] = getattr(pi, "client_secret", None)
    if not client_secret:
        # Retrieve to ensure we have it (some Stripe flows do not return it on all calls)
        pi = stripe.PaymentIntent.retrieve(pi.id)
        client_secret = getattr(pi, "client_secret", None)
    if not client_secret:
        raise RuntimeError("Stripe PaymentIntent missing client_secret")
    return pi.id, client_secret


def retrieve_client_secret(payment_intent_id: str) -> str:
    """
    Retrieve a client_secret for an existing PaymentIntent.
    If Stripe is disabled (e.g., tests), synthesize a fake secret deterministically.
    """
    if not stripe_enabled():
        # Synthesize a deterministic secret for UI rendering in tests
        return f"test_client_secret_{payment_intent_id}"

    _init_stripe()
    pi = stripe.PaymentIntent.retrieve(payment_intent_id)
    client_secret: Optional[str] = getattr(pi, "client_secret", None)
    if not client_secret:
        raise RuntimeError("Stripe PaymentIntent missing client_secret")
    return client_secret

@router.get("/api/v1/bookings/{booking_id}/payment_info", response_model=schemas.PaymentInfoResponse)
def get_payment_info(
    booking_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_tenant),
) -> schemas.PaymentInfoResponse:
    """
    Ensure a PaymentIntent exists for a pending_payment booking and return its client_secret + expires_at.
    Only the booking's tenant may access this.
    """
    booking = db.get(models.Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.guest_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    if booking.status != "pending_payment":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is not pending payment")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    expires_at = booking.expires_at
    if expires_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment hold expired")
    # Normalize to timezone-aware (assume UTC) to avoid naive vs aware comparison issues
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment hold expired")

    client_secret: Optional[str] = None
    if not booking.payment_intent_id:
        idem_key = f"booking:{booking.id}:v{booking.version or 1}"
        pi_id, client_secret = create_payment_intent(
            amount_cents=booking.total_cents,
            currency=booking.currency,
            booking_id=booking.id,
            property_id=booking.property_id,
            idempotency_key=idem_key,
        )
        booking.payment_intent_id = pi_id
        db.add(booking)
        db.commit()
    else:
        # If Stripe enabled, inspect existing PaymentIntent status:
        # - canceled: create a fresh PaymentIntent and update booking
        # - succeeded: finalize booking (mirror webhook) and stop pay flow
        if stripe_enabled():
            try:
                pi = stripe.PaymentIntent.retrieve(booking.payment_intent_id)
                pi_status = getattr(pi, "status", None)
            except Exception:
                pi = None
                pi_status = None

            if pi_status == "canceled":
                # Create a new intent for a canceled/invalidated PI
                idem_key = f"booking:{booking.id}:v{(booking.version or 1) + 1}"
                new_pi_id, client_secret = create_payment_intent(
                    amount_cents=booking.total_cents,
                    currency=booking.currency,
                    booking_id=booking.id,
                    property_id=booking.property_id,
                    idempotency_key=idem_key,
                )
                booking.payment_intent_id = new_pi_id
                booking.version = (booking.version or 1) + 1
                db.add(booking)
                db.commit()
            elif pi_status == "succeeded":
                # Treat as paid: finalize booking just like webhook would (idempotent)
                # Expiry guard
                if expires_at <= now:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment hold expired")
                # Defensive overlap vs confirmed
                if _has_confirmed_overlap(db, booking.property_id, booking.start_date, booking.end_date):
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Overlap conflict")
                current_version = booking.version or 1
                rows = (
                    db.query(models.Booking)
                    .filter(
                        models.Booking.id == booking.id,
                        models.Booking.version == current_version,
                        models.Booking.status == "pending_payment",
                    )
                    .update(
                        {
                            models.Booking.status: "confirmed",
                            models.Booking.version: current_version + 1,
                        },
                        synchronize_session=False,
                    )
                )
                if rows:
                    db.commit()
                else:
                    db.rollback()
                # Surface a user-friendly error; UI should refresh to reflect confirmed
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking already paid")

    if client_secret is None:
        client_secret = retrieve_client_secret(booking.payment_intent_id)  # type: ignore[arg-type]
    return schemas.PaymentInfoResponse(
        booking_id=booking.id,
        client_secret=client_secret,
        expires_at=expires_at,  # type: ignore[arg-type]
    )


@router.post("/api/v1/bookings/{booking_id}/finalize_payment")
def finalize_payment(
    booking_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_tenant),
):
    """
    Explicitly finalize a booking after client-side confirmation when webhooks are not used.
    Idempotent: returns the confirmed booking if already confirmed, 202 if still processing.
    """
    # Lookup and basic auth
    booking: Optional[models.Booking] = db.get(models.Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.guest_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    # If already confirmed, short-circuit
    if booking.status == "confirmed":
        return schemas.BookingRead.model_validate(booking)

    if booking.status != "pending_payment":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is not pending payment")

    # Hold window must still be valid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    exp = booking.expires_at
    if exp is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment hold expired")
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment hold expired")

    # Stripe required to check PaymentIntent status
    if not stripe_enabled():
        return {"status": "stripe_disabled"}

    _init_stripe()
    if not booking.payment_intent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing payment_intent")

    try:
        pi = stripe.PaymentIntent.retrieve(booking.payment_intent_id)
        pi_status: Optional[str] = getattr(pi, "status", None)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to retrieve PaymentIntent: {exc}")

    if pi_status == "succeeded":
        # Defensive overlap vs confirmed (should not happen, but guard)
        if _has_confirmed_overlap(db, booking.property_id, booking.start_date, booking.end_date):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Overlap conflict")

        # Idempotent finalize (mirror webhook)
        current_version = booking.version or 1
        rows = (
            db.query(models.Booking)
            .filter(
                models.Booking.id == booking.id,
                models.Booking.version == current_version,
                models.Booking.status == "pending_payment",
            )
            .update(
                {
                    models.Booking.status: "confirmed",
                    models.Booking.version: current_version + 1,
                },
                synchronize_session=False,
            )
        )
        if rows == 0:
            db.rollback()
            latest = db.query(models.Booking).get(booking.id)
            if latest and latest.status == "confirmed":
                return schemas.BookingRead.model_validate(latest)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version conflict")
        db.commit()
        db.refresh(booking)
        return schemas.BookingRead.model_validate(booking)

    if pi_status in ("processing", "requires_action", "requires_payment_method", "requires_confirmation"):
        # Let client retry/poll
        return {"status": "processing"}

    if pi_status == "canceled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment cancelled")

    # Unknown/unexpected status
    return {"status": pi_status or "unknown"}


def _has_confirmed_overlap(db: Session, property_id: int, start_date, end_date) -> bool:
    """
    Overlap check against confirmed bookings only:
    NOT (existing.end_date <= start_date OR existing.start_date >= end_date)
    """
    exists = (
        db.query(models.Booking.id)
        .filter(
            models.Booking.property_id == property_id,
            models.Booking.status == "confirmed",
            ~(
                (models.Booking.end_date <= start_date)
                | (models.Booking.start_date >= end_date)
            ),
        )
        .first()
    )
    return exists is not None


@router.post("/payments/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
) -> dict:
    """
    Verify Stripe signature and handle payment_intent.succeeded (idempotent finalize).
    Returns 200 on success or safe no-ops. 4xx only for invalid payload/signature.
    """
    # If Stripe disabled, accept as no-op for local testing convenience
    if not stripe_enabled():
        return {"status": "stripe_disabled"}

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook secret not configured")

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=payload.decode("utf-8"),
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid webhook: {exc}")

    event_type: str = getattr(event, "type", "") or ""
    obj: Any = getattr(event, "data", {}).get("object") if hasattr(event, "data") else None

    if event_type == "payment_intent.succeeded" and obj:
        payment_intent_id = getattr(obj, "id", None) or (obj.get("id") if isinstance(obj, dict) else None)
        if not payment_intent_id:
            # Malformed event
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing payment_intent id")

        # Lookup booking by payment_intent_id
        booking: Optional[models.Booking] = (
            db.query(models.Booking).filter(models.Booking.payment_intent_id == payment_intent_id).first()
        )
        if not booking:
            # Unknown intent; accept to avoid retries storm but log if needed
            return {"status": "unknown_intent"}

        # Preconditions
        if booking.status == "confirmed":
            return {"status": "already_confirmed"}  # idempotent

        if booking.status != "pending_payment":
            return {"status": "invalid_status"}  # ignore

        # Expiry guard
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        exp = booking.expires_at
        if exp is None:
            return {"status": "expired"}  # ignore late
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            return {"status": "expired"}  # ignore late

        # Defensive overlap check vs confirmed
        if _has_confirmed_overlap(db, booking.property_id, booking.start_date, booking.end_date):
            return {"status": "overlap_conflict"}  # ignore/alert; do not confirm

        # Optimistic concurrency finalize
        current_version = booking.version or 1
        rows = (
            db.query(models.Booking)
            .filter(
                models.Booking.id == booking.id,
                models.Booking.version == current_version,
                models.Booking.status == "pending_payment",
            )
            .update(
                {
                    models.Booking.status: "confirmed",
                    models.Booking.version: current_version + 1,
                },
                synchronize_session=False,
            )
        )
        if rows == 0:
            # Re-read to determine state
            db.rollback()  # rollback pending transaction to clear write intents
            latest = db.query(models.Booking).get(booking.id)
            if latest and latest.status == "confirmed":
                return {"status": "already_confirmed"}
            # Could retry limited times in a real system; here just surface a conflict-ish outcome
            return {"status": "version_conflict"}
        db.commit()
        return {"status": "confirmed"}

    # Optionally log failures, but do not error
    if event_type == "payment_intent.payment_failed":
        return {"status": "payment_failed_observed"}

    # Other events ignored
    return {"status": "ignored"}
