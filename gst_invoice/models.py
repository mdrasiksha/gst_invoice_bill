"""Dataclasses used by the GST Invoice Generator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(slots=True)
class Company:
    seller_name: str
    gstin: str
    address: str
    phone: str = ""
    email: str = ""
    state_code: str = "29"
    logo_path: str = ""
    id: Optional[int] = None


@dataclass(slots=True)
class Customer:
    customer_name: str
    gstin: str
    address: str
    phone: str = ""
    state_code: str = ""
    id: Optional[int] = None


@dataclass(slots=True)
class InvoiceItem:
    item_name: str
    hsn_sac: str
    quantity: float
    unit_price: float
    gst_percentage: float
    taxable_value: float = 0.0
    gst_amount: float = 0.0
    total_amount: float = 0.0
    id: Optional[int] = None

    def calculate(self) -> None:
        self.taxable_value = round(self.quantity * self.unit_price, 2)
        self.gst_amount = round(self.taxable_value * self.gst_percentage / 100, 2)
        self.total_amount = round(self.taxable_value + self.gst_amount, 2)


@dataclass(slots=True)
class Invoice:
    invoice_number: str
    invoice_date: date
    due_date: date
    place_of_supply: str
    state_code: str
    company: Company
    customer: Customer
    items: list[InvoiceItem] = field(default_factory=list)
    taxable_amount: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    grand_total: float = 0.0
    pdf_path: str = ""
    id: Optional[int] = None

    @property
    def is_intrastate(self) -> bool:
        return (self.company.state_code or "") == (self.state_code or "")
