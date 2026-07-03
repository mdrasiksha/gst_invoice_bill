"""Shared finalized invoice view/PDF data builder."""
from __future__ import annotations

from typing import Any

from .models import Invoice
from .tax_service import calculate_and_finalize_invoice_tax


def build_invoice_data(invoice: Invoice) -> dict[str, Any]:
    """Return the single finalized invoice data object used by preview and PDF."""
    return calculate_and_finalize_invoice_tax(invoice, persist=True)
