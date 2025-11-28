from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .db import Base, engine
from .routes.properties import router as properties_router
from .routes.auth import router as auth_router

app = FastAPI(title="StayCircle API", version="0.1.0")

# CORS for frontend; configurable via CORS_ORIGINS env (comma-separated)
origins_env = os.getenv("CORS_ORIGINS")
if origins_env:
    origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    origins = ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Create tables automatically on startup for Sprint 1
    Base.metadata.create_all(bind=engine)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# API routes
app.include_router(auth_router, prefix="", tags=["auth"])
app.include_router(properties_router, prefix="/api/v1", tags=["properties"])
