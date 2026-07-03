"""Single GST tax calculation/finalization service for invoices."""
from __future__ import annotations

import logging
from typing import Any

from .models import Invoice
from .utils import money, normalize_state_name, state_code_from_state
from .validators import ALLOWED_GST_RATES

logger = logging.getLogger(__name__)
DEFAULT_SUPPLIER_STATE = "Karnataka"


def _code_from_state(value: str | None) -> str:
    state = normalize_state_name(value or "")
    return (state_code_from_state(state) or "").strip().zfill(2) if state else ""


def _supplier_state(invoice: Invoice) -> str:
    state = normalize_state_name(getattr(invoice.company, "state", "") or "")
    return state or DEFAULT_SUPPLIER_STATE


def _customer_state(invoice: Invoice) -> str:
    return normalize_state_name(getattr(invoice.customer, "state", "") or invoice.place_of_supply or "")


def _supplier_code(invoice: Invoice, supplier_state: str) -> str:
    return ((getattr(invoice.company, "state_code", "") or "").strip().zfill(2) if getattr(invoice.company, "state_code", "") else "") or _code_from_state(supplier_state)


def _customer_code(invoice: Invoice, customer_state: str) -> str:
    return ((invoice.state_code or getattr(invoice.customer, "state_code", "") or "").strip().zfill(2) if (invoice.state_code or getattr(invoice.customer, "state_code", "")) else "") or _code_from_state(customer_state)


def calculate_and_finalize_invoice_tax(invoice: Invoice, *, persist: bool = True) -> dict[str, Any]:
    """Calculate item totals and return the one finalized invoice tax object.

    The returned object is the single source of truth for form persistence,
    preview rendering, and PDF rendering.  State comparison is based on a
    normalized supplier/customer state snapshot instead of independently using
    saved company settings in one path and submitted/customer data in another.
    """
    taxable = gst_total = 0.0
    items = list(invoice.items or [])
    max_gst_rate = 0.0
    for item in items:
        if item.quantity <= 0 or item.unit_price < 0:
            raise ValueError("Quantity must be positive and prices cannot be negative.")
        if item.gst_percentage not in ALLOWED_GST_RATES:
            raise ValueError("GST rate must be one of 0%, 5%, 12%, 18% or 28%.")
        item.calculate()
        taxable += item.taxable_value
        gst_total += item.gst_amount
        max_gst_rate = max(max_gst_rate, float(item.gst_percentage or 0))

    supplier_state = _supplier_state(invoice)
    customer_state = _customer_state(invoice)
    supplier_state_code = _supplier_code(invoice, supplier_state)
    customer_state_code = _customer_code(invoice, customer_state)
    same_state = bool(supplier_state_code and customer_state_code and supplier_state_code == customer_state_code)
    tax_type = "CGST_SGST" if same_state else "IGST"

    taxable_amount = float(money(taxable))
    if same_state:
        cgst_amount = float(money(gst_total / 2))
        sgst_amount = float(money(gst_total / 2))
        igst_amount = 0.0
    else:
        cgst_amount = sgst_amount = 0.0
        igst_amount = float(money(gst_total))
    total_tax_amount = float(money(cgst_amount + sgst_amount + igst_amount))
    unrounded = float(money(taxable_amount + total_tax_amount))
    grand_total = float(money(round(unrounded)))
    round_off = float(money(grand_total - unrounded))

    if persist:
        invoice.taxable_amount = taxable_amount
        invoice.cgst = cgst_amount
        invoice.sgst = sgst_amount
        invoice.igst = igst_amount
        invoice.round_off = round_off
        invoice.grand_total = grand_total

    totals = {
        "taxable_amount": taxable_amount,
        "tax_rate": max_gst_rate,
        "cgst": cgst_amount,
        "sgst": sgst_amount,
        "igst": igst_amount,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": igst_amount,
        "total_tax_amount": total_tax_amount,
        "round_off": round_off,
        "grand_total": grand_total,
        "max_gst_rate": max_gst_rate,
    }
    data = {
        "invoice": invoice,
        "company": invoice.company,
        "customer": invoice.customer,
        "items": items,
        "invoice_items": items,
        "totals": totals,
        "supplier_state": supplier_state,
        "customer_state": customer_state,
        "supplier_state_code": supplier_state_code,
        "customer_state_code": customer_state_code,
        "same_state": same_state,
        "tax_type": tax_type,
        "taxable_amount": taxable_amount,
        "tax_rate": max_gst_rate,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "igst_amount": igst_amount,
        "total_tax_amount": total_tax_amount,
        "grand_total": grand_total,
    }
    logger.info("Finalized invoice tax breakdown", extra={k: data[k] for k in ["supplier_state", "customer_state", "tax_type", "taxable_amount", "tax_rate", "cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "grand_total"]} | {"invoice_id": invoice.id, "invoice_number": invoice.invoice_number})
    return data
