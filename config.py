"""Application configuration for GST Smart."""
from __future__ import annotations

import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def database_uri() -> str:
    """Return SQLAlchemy database URI with Render PostgreSQL normalization."""
    uri = (os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'instance' / 'gst_invoice_saas.db'}").strip()
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


class Config:
    """Default Flask configuration."""

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        os.environ.get("GST_SMART_SECRET_KEY", os.environ.get("GST_INVOICE_SECRET_KEY", secrets.token_hex(32))),
    )
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
