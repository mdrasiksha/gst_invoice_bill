"""Shared finalized invoice view/PDF data builder."""
from __future__ import annotations

from typing import Any

from .models import Company, Invoice
from .tax_service import calculate_and_finalize_invoice_tax


def build_invoice_data(invoice: Invoice) -> dict[str, Any]:
    """Return the single finalized invoice data object used by preview and PDF."""
    return calculate_and_finalize_invoice_tax(invoice, persist=True)


def present(value: object) -> bool:
    """Return True when a display value contains non-whitespace text."""
    return bool(str(value or "").strip())


def company_address(company: Company) -> str:
    """Return a clean, comma-separated company address for previews and PDFs."""
    return ", ".join(
        str(part).strip()
        for part in [company.address, company.city, company.state, company.pin_code]
        if present(part)
    )


def company_detail_lines(company: Company) -> list[str]:
    """Return company detail lines without empty labels or placeholder punctuation."""
    lines: list[str] = []
    if present(company.gstin):
        lines.append(f"GSTIN: {str(company.gstin).strip()}")
    address = company_address(company)
    if present(address):
        lines.append(address)
    contact_bits = []
    if present(company.phone):
        contact_bits.append(f"Phone: {str(company.phone).strip()}")
    if present(company.email):
        contact_bits.append(f"Email: {str(company.email).strip()}")
    if contact_bits:
        lines.append(" · ".join(contact_bits))
    return lines
