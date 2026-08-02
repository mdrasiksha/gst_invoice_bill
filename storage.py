"""Cloudinary-backed image storage helpers for GST Smart uploads."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent

# Load local development variables from .env without overriding Render's environment.
load_dotenv(BASE_DIR / ".env", override=False)

_CONFIGURED = False


def _env(name: str) -> str:
    """Return a normalized environment value, trimming accidental whitespace."""
    return (os.getenv(name) or "").strip()


def _cloudinary_credentials() -> tuple[str, str, str]:
    """Return individual Cloudinary credentials from the process environment."""
    return (
        _env("CLOUDINARY_CLOUD_NAME"),
        _env("CLOUDINARY_API_KEY"),
        _env("CLOUDINARY_API_SECRET"),
    )


def cloudinary_environment_status() -> dict[str, Any]:
    """Return non-secret Cloudinary environment status for diagnostics."""
    cloud_name, api_key, api_secret = _cloudinary_credentials()
    return {
        "cloudinary_url_present": bool(_env("CLOUDINARY_URL")),
        "cloud_name_present": bool(cloud_name),
        "cloud_name": cloud_name or None,
        "api_key_present": bool(api_key),
        "api_secret_present": bool(api_secret),
    }


def is_cloudinary_configured() -> bool:
    """Return whether the environment contains a supported Cloudinary configuration."""
    cloudinary_url = _env("CLOUDINARY_URL")
    cloud_name, api_key, api_secret = _cloudinary_credentials()
    return bool(cloudinary_url or (cloud_name and api_key and api_secret))


def _configure_cloudinary() -> None:
    """Configure Cloudinary from Render or local development environment variables."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    status = cloudinary_environment_status()
    logger.info("Cloudinary configuration detected", extra=status)

    cloudinary_url = _env("CLOUDINARY_URL")
    if cloudinary_url:
        # The Cloudinary SDK reads CLOUDINARY_URL from the process environment.
        os.environ["CLOUDINARY_URL"] = cloudinary_url
        cloudinary.config(secure=True)
        _CONFIGURED = True
        return

    cloud_name, api_key, api_secret = _cloudinary_credentials()
    if not (cloud_name and api_key and api_secret):
        logger.error("Cloudinary configuration is incomplete", extra=status)
        raise RuntimeError(
            "Cloudinary is not configured. Set CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
        )

    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)
    _CONFIGURED = True


def upload_image(file, folder: str) -> dict[str, str]:
    """Upload an image file object to Cloudinary and return its secure URL and public ID."""
    _configure_cloudinary()
    file.stream.seek(0)
    result: dict[str, Any] = cloudinary.uploader.upload(file.stream, folder=folder, resource_type="image")
    secure_url = result.get("secure_url")
    public_id = result.get("public_id")
    if not secure_url or not public_id:
        raise RuntimeError("Cloudinary upload did not return a secure URL and public ID.")
    return {"url": secure_url, "public_id": public_id}


def delete_image(public_id: str | None) -> None:
    """Delete a Cloudinary image by public ID; blank IDs are ignored."""
    if not public_id:
        return
    _configure_cloudinary()
    cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
