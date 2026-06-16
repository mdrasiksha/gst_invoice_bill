"""GST invoice calculation service."""
from __future__ import annotations

from .models import Invoice
from .utils import money
from .validators import ALLOWED_GST_RATES


def calculate_invoice(invoice: Invoice) -> Invoice:
    """Calculate taxable values and Indian GST split."""
    taxable = gst_total = 0.0
    for item in invoice.items:
        if item.quantity <= 0 or item.unit_price < 0:
            raise ValueError("Quantity must be positive and prices cannot be negative.")
        if item.gst_percentage not in ALLOWED_GST_RATES:
            raise ValueError("GST rate must be one of 0%, 5%, 12%, 18% or 28%.")
        item.calculate()
        taxable += item.taxable_value
        gst_total += item.gst_amount
    invoice.taxable_amount = float(money(taxable))
    if invoice.is_intrastate:
        invoice.cgst = float(money(gst_total / 2))
        invoice.sgst = float(money(gst_total / 2))
        invoice.igst = 0.0
    else:
        invoice.cgst = invoice.sgst = 0.0
        invoice.igst = float(money(gst_total))
    unrounded = float(money(invoice.taxable_amount + invoice.cgst + invoice.sgst + invoice.igst))
    rounded = round(unrounded)
    invoice.round_off = float(money(rounded - unrounded))
    invoice.grand_total = float(money(rounded))
    return invoice
