"""Create a sample invoice PDF using the bundled LaunchReadyCVs company data."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gst_invoice.database import Database
from gst_invoice.invoice_generator import calculate_invoice
from gst_invoice.models import Customer, Invoice, InvoiceItem
from gst_invoice.pdf_generator import PDFGenerator


def main() -> None:
    db = Database()
    company = db.get_company()
    invoice = Invoice(
        invoice_number=db.next_invoice_number(),
        invoice_date=date.today(),
        due_date=date.today(),
        place_of_supply="Karnataka",
        state_code="29",
        company=company,
        customer=Customer(
            "Acme Retail Pvt Ltd",
            "29AAECA1234F1Z1",
            "MG Road, Bengaluru, Karnataka",
            "+91 90000 11111",
            "29",
        ),
        items=[
            InvoiceItem("Resume Writing Service", "998311", 2, 2500, 18),
            InvoiceItem("LinkedIn Profile Optimization", "998313", 1, 1500, 18),
        ],
    )
    calculate_invoice(invoice)
    invoice.pdf_path = PDFGenerator().generate(invoice)
    db.save_invoice(invoice)
    print(invoice.pdf_path)


if __name__ == "__main__":
    main()
