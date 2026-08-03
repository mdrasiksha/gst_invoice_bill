"""Helpers for safely loading images into ReportLab."""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import requests
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)


def reportlab_image_reader(source: str | Path | None, *, timeout: int = 15) -> ImageReader | None:
    """Return an ImageReader for a local path or remote image URL.

    Remote Cloudinary assets must be downloaded first because ReportLab can fail
    when it is asked to open HTTPS resources directly. Failures are logged and
    represented as ``None`` so callers can skip optional images without aborting
    PDF generation.
    """
    if not source:
        return None

    source_value = str(source).strip()
    if not source_value:
        return None

    try:
        if source_value.startswith(("http://", "https://")):
            response = requests.get(source_value, timeout=timeout)
            response.raise_for_status()
            return ImageReader(BytesIO(response.content))

        path = Path(source_value)
        if not path.exists():
            logger.warning("Skipping missing local image", extra={"image_source": source_value})
            return None
        return ImageReader(str(path))
    except Exception:
        logger.warning("Unable to load image for ReportLab", exc_info=True, extra={"image_source": source_value})
        return None
