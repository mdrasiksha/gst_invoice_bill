"""Shared finalized invoice view/PDF data builder."""
from __future__ import annotations

import logging
from typing import Any

from .models import Invoice
from .utils import normalize_state_name, state_code_from_state

logger = logging.getLogger(__name__)


def _state_code(value: str | None) -> str:
    return (state_code_from_state(normalize_state_name(value or "")) or "").strip().zfill(2) if value else ""


def build_invoice_data(invoice: Invoice) -> dict[str, Any]:
    """Return the single finalized invoice data object used by preview and PDF.

    This function intentionally uses the tax amounts already stored on the invoice.
    It only decides which tax split should be displayed from the finalized supplier
    and customer state values, so PDF generation never recalculates tax differently
    from the persisted/previewed invoice.
    """
    items = list(invoice.items or [])
    supplier_state = normalize_state_name(getattr(invoice.company, "state", "") or "")
    customer_state = normalize_state_name(getattr(invoice.customer, "state", "") or invoice.place_of_supply or "")
    supplier_state_code = (getattr(invoice.company, "state_code", "") or _state_code(supplier_state)).strip().zfill(2)
    customer_state_code = (invoice.state_code or getattr(invoice.customer, "state_code", "") or _state_code(customer_state)).strip().zfill(2)
    same_state = bool(supplier_state_code and customer_state_code and supplier_state_code == customer_state_code)
    tax_type = "CGST_SGST" if same_state else "IGST"
    max_gst_rate = max((float(item.gst_percentage or 0) for item in items), default=0.0)
    totals = {
        "taxable_amount": float(invoice.taxable_amount or 0),
        "cgst": float(invoice.cgst or 0),
        "sgst": float(invoice.sgst or 0),
        "igst": float(invoice.igst or 0),
        "round_off": float(invoice.round_off or 0),
        "grand_total": float(invoice.grand_total or 0),
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
    }
    logger.info(
        "Finalized invoice tax breakdown",
        extra={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "supplier_state": supplier_state,
            "customer_state": customer_state,
            "tax_type": tax_type,
            "cgst_amount": totals["cgst"],
            "sgst_amount": totals["sgst"],
            "igst_amount": totals["igst"],
        },
    )
    return data
