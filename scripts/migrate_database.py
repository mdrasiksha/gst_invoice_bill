"""Run GST Smart safe database migrations for deployed environments.

This script is intentionally additive: it creates missing tables, adds missing
backwards-compatible columns, and optionally bootstraps the configured admin
user without deleting existing data.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, ensure_admin_user, ensure_database_columns
from gst_invoice.models import db


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_database_columns()
        ensure_admin_user()
    print("Database migration completed successfully.")
