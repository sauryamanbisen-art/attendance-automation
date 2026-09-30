"""Attendance Automation Platform - FastAPI Application Entry Point."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.database import init_db

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger("attendance_automation.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    logger.info("Initializing Attendance Automation application...")
    init_db()
    logger.info("Database schema initialized.")
    yield
    logger.info("Shutting down Attendance Automation application.")


app = FastAPI(
    title=settings.app_name,
    description="Open-Source, Local-First Attendance Monitoring & Correction Automation Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for local development and dashboard UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Mount frontend static directory if it exists
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/dashboard", tags=["Dashboard"])
def dashboard() -> FileResponse:
    """Serve the local-first web dashboard."""
    index_file = os.path.join(frontend_dir, "index.html")
    return FileResponse(index_file)


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def favicon() -> Response:
    """Return 204 No Content for favicon to prevent 404 in browser console."""
    return Response(status_code=204)


@app.get("/", tags=["Root"])
def root_status() -> dict[str, str | bool]:
    """Root endpoint verifying application status and local readiness."""
    return {
        "status": "online",
        "app": settings.app_name,
        "version": "0.1.0",
        "docs_url": "/docs",
        "dashboard_url": "/dashboard",
        "dry_run": settings.dry_run,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
