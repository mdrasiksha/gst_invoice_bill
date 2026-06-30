"""Validation helpers for invoice input."""
from __future__ import annotations

from datetime import date

from .models import Company, Customer, InvoiceItem
from .utils import parse_date, state_code_from_gstin, state_code_from_state, validate_email, validate_gstin, validate_phone

ALLOWED_GST_RATES = (0.0, 5.0, 12.0, 18.0, 28.0)


def parse_positive_float(value: str, field: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid number.") from exc
    if allow_zero:
        if number < 0:
            raise ValueError(f"{field} cannot be negative.")
    elif number <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    return number


def parse_gst_rate(value: str) -> float:
    rate = parse_positive_float(value, "GST rate", allow_zero=True)
    if rate not in ALLOWED_GST_RATES:
        allowed = ", ".join(f"{rate:g}%" for rate in ALLOWED_GST_RATES)
        raise ValueError(f"GST rate must be one of: {allowed}.")
    return rate


def validate_company(company: Company) -> None:
    if not company.seller_name:
        raise ValueError("Company name is required.")
    if not validate_gstin(company.gstin, optional=True):
        raise ValueError("Company GSTIN is invalid.")
    if company.state and not state_code_from_state(company.state):
        raise ValueError("Company state must be a valid Indian state or union territory.")
    if company.state and company.gstin and state_code_from_gstin(company.gstin) != state_code_from_state(company.state):
        raise ValueError("Company state does not match the GSTIN state code.")
    if company.phone and not validate_phone(company.phone):
        raise ValueError("Company phone number is invalid.")
    if company.email and not validate_email(company.email):
        raise ValueError("Company email is invalid.")


def validate_customer(customer: Customer) -> None:
    if not validate_gstin(customer.gstin, optional=True):
        raise ValueError("Customer GSTIN is invalid.")
    if customer.state and not state_code_from_state(customer.state):
        raise ValueError("Customer state must be a valid Indian state or union territory.")
    if customer.state and customer.state_code and customer.state_code.zfill(2) != state_code_from_state(customer.state):
        raise ValueError("Customer state does not match the state code.")
    if customer.gstin and customer.state and state_code_from_gstin(customer.gstin) != state_code_from_state(customer.state):
        raise ValueError("Customer state does not match the GSTIN state code.")
    if customer.phone and not validate_phone(customer.phone):
        raise ValueError("Customer phone number is invalid.")
    if customer.email and not validate_email(customer.email):
        raise ValueError("Customer email is invalid.")


def validate_invoice_dates(invoice_date: date, due_date: date) -> None:
    if due_date < invoice_date:
        raise ValueError("Due date cannot be earlier than the invoice date.")


def validate_item(item: InvoiceItem) -> None:
    if not item.item_name:
        raise ValueError("Every product row requires an item name.")
    if item.quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if item.unit_price < 0:
        raise ValueError("Unit price cannot be negative.")
    if item.gst_percentage not in ALLOWED_GST_RATES:
        raise ValueError("Invalid GST percentage selected.")


def parse_required_date(value: str, field: str) -> date:
    try:
        return parse_date(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD format.") from exc
