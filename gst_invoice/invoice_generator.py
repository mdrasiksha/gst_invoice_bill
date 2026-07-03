"""GST invoice calculation service."""
from __future__ import annotations

from .models import Invoice
from .tax_service import calculate_and_finalize_invoice_tax


def calculate_invoice(invoice: Invoice) -> Invoice:
    """Calculate taxable values and Indian GST split using the shared tax service."""
    calculate_and_finalize_invoice_tax(invoice, persist=True)
    return invoice
