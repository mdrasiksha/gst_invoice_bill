"""Cloudinary-backed image storage helpers for GST Smart uploads."""
from __future__ import annotations

import os
from typing import Any

import cloudinary
import cloudinary.uploader


def _configure_cloudinary() -> None:
    """Configure Cloudinary from Render environment variables."""
    if os.getenv("CLOUDINARY_URL"):
        cloudinary.config(secure=True)
        return
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not (cloud_name and api_key and api_secret):
        raise RuntimeError("Cloudinary is not configured. Set CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET.")
    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)


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
