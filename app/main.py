from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import threading
import time

from .db import Base, engine
from .routes.properties import router as properties_router
from .routes.auth import router as auth_router
from .routes.bookings import router as bookings_router
from .payments import router as payments_router
from .sweepers import sweep_expired_bookings


def _start_expiry_sweeper(interval_seconds: int = 60) -> None:
    """
    Background thread that sweeps expired pending_payment bookings every interval.
    """
    def _loop() -> None:
        while True:
            try:
                sweep_expired_bookings()
            except Exception:
                # Avoid crashing the thread on transient DB errors; will try again next tick.
                pass
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="booking-expiry-sweeper", daemon=True)
    t.start()

app = FastAPI(title="StayCircle API", version="0.1.0")

# CORS for frontend; configurable via CORS_ORIGINS env (comma-separated)
# Supports wildcard "*" for local dev, or a CSV list of origins.
origins_env = os.getenv("CORS_ORIGINS")
if origins_env:
    parsed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    # Default to localhost + 127.0.0.1 for convenience
    parsed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Normalize and handle wildcard by mapping to explicit dev origins so credentials can work
dev_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if "*" in parsed_origins:
    allow_list = dev_default_origins
else:
    allow_list = parsed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # For SQLite dev fallback, auto-create tables; for MySQL we rely on Alembic migrations.
    if os.getenv("DATABASE_URL", "sqlite:///./data.db").startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    # Start background sweeper for expired holds (runs every 60s)
    _start_expiry_sweeper(interval_seconds=60)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# API routes
app.include_router(auth_router, prefix="", tags=["auth"])
app.include_router(payments_router, prefix="", tags=["payments"])
app.include_router(properties_router, prefix="/api/v1", tags=["properties"])
app.include_router(bookings_router, prefix="/api/v1", tags=["bookings"])
