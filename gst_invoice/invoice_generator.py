"""GST invoice calculation service."""
from __future__ import annotations

from .models import Invoice
from .utils import money


def calculate_invoice(invoice: Invoice) -> Invoice:
    """Calculate item values and GST split according to Indian intra/inter-state rules."""
    taxable = gst_total = 0.0
    for item in invoice.items:
        if item.quantity <= 0 or item.unit_price < 0 or item.gst_percentage < 0:
            raise ValueError("Quantity must be positive and prices/GST rates cannot be negative.")
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
    invoice.grand_total = float(money(invoice.taxable_amount + invoice.cgst + invoice.sgst + invoice.igst))
    return invoice
