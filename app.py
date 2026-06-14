"""Bootstrap web application for the GST Invoice Generator."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from gst_invoice.database import Database
from gst_invoice.invoice_generator import calculate_invoice
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem
from gst_invoice.pdf_generator import PDFGenerator
from gst_invoice.utils import amount_to_words, state_code_from_gstin
from gst_invoice.validators import (
    ALLOWED_GST_RATES,
    parse_gst_rate,
    parse_positive_float,
    parse_required_date,
    validate_company,
    validate_customer,
    validate_invoice_dates,
    validate_item,
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "gst_invoice" / "assets" / "logos"
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg"}

app = Flask(__name__)
app.secret_key = os.environ.get("GST_INVOICE_SECRET_KEY", "gst-invoice-generator-dev-key")
db = Database()
pdf = PDFGenerator()


def save_logo(upload) -> str:
    if not upload or not upload.filename:
        return ""
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError("Logo must be a PNG or JPG image.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(upload.filename)
    target = UPLOAD_DIR / filename
    upload.save(target)
    return str(target)


def build_invoice_from_form(form, files) -> Invoice:
    current_company = db.get_company()
    logo_path = save_logo(files.get("company_logo")) or form.get("existing_logo", "").strip()
    company_gstin = form.get("company_gstin", "").strip().upper()
    company = Company(
        seller_name=form.get("company_name", "").strip(),
        gstin=company_gstin,
        address=form.get("company_address", "").strip(),
        phone=form.get("company_phone", "").strip(),
        email=form.get("company_email", "").strip(),
        state_code=state_code_from_gstin(company_gstin) or current_company.state_code,
        logo_path=logo_path,
        id=current_company.id,
    )
    customer_gstin = form.get("customer_gstin", "").strip().upper()
    state_code = form.get("state_code", "").strip() or state_code_from_gstin(customer_gstin) or company.state_code
    customer = Customer(
        customer_name=form.get("customer_name", "").strip(),
        gstin=customer_gstin,
        address=form.get("customer_address", "").strip(),
        phone=form.get("customer_phone", "").strip(),
        state_code=state_code,
    )
    invoice_date = parse_required_date(form.get("invoice_date", ""), "Invoice date")
    due_date = parse_required_date(form.get("due_date", ""), "Due date")
    items: list[InvoiceItem] = []
    names = form.getlist("item_name[]")
    for idx, name in enumerate(names):
        if not any((name, form.getlist("hsn_sac[]")[idx], form.getlist("quantity[]")[idx], form.getlist("unit_price[]")[idx])):
            continue
        item = InvoiceItem(
            item_name=name.strip(),
            hsn_sac=form.getlist("hsn_sac[]")[idx].strip(),
            quantity=parse_positive_float(form.getlist("quantity[]")[idx], "Quantity"),
            unit_price=parse_positive_float(form.getlist("unit_price[]")[idx], "Unit price", allow_zero=True),
            gst_percentage=parse_gst_rate(form.getlist("gst_percentage[]")[idx]),
        )
        validate_item(item)
        items.append(item)
    if not items:
        raise ValueError("Add at least one product or service row.")
    validate_company(company)
    validate_customer(customer)
    validate_invoice_dates(invoice_date, due_date)
    invoice = Invoice(
        invoice_number=form.get("invoice_number", "").strip() or db.next_invoice_number(),
        invoice_date=invoice_date,
        due_date=due_date,
        place_of_supply=form.get("place_of_supply", "").strip() or "Karnataka",
        state_code=state_code,
        company=company,
        customer=customer,
        items=items,
    )
    return calculate_invoice(invoice)


@app.route("/", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        try:
            invoice = build_invoice_from_form(request.form, request.files)
            db.save_company(invoice.company)
            invoice.company = db.get_company()
            invoice.pdf_path = pdf.generate(invoice)
            db.save_invoice(invoice)
            flash(f"Invoice {invoice.invoice_number} saved successfully.", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            flash(str(exc), "danger")
    company = db.get_company()
    invoices = db.list_invoices(request.args.get("q", ""))
    defaults = {
        "invoice_number": db.next_invoice_number(),
        "invoice_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=15)).isoformat(),
    }
    return render_template("dashboard.html", company=company, invoices=invoices, defaults=defaults, gst_rates=ALLOWED_GST_RATES, amount_to_words=amount_to_words)


@app.route("/invoice/<invoice_number>")
def invoice_preview(invoice_number: str):
    invoice = db.get_invoice(invoice_number)
    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("invoice_preview.html", invoice=invoice, amount_to_words=amount_to_words)


@app.route("/invoice/<invoice_number>/pdf")
def download_pdf(invoice_number: str):
    invoice = db.get_invoice(invoice_number)
    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("dashboard"))
    path = Path(invoice.pdf_path) if invoice.pdf_path else Path(pdf.generate(invoice))
    if not path.exists():
        path = Path(pdf.generate(invoice))
    return send_file(path, as_attachment=True, download_name=f"{invoice.invoice_number}.pdf")


@app.route("/invoice/<invoice_number>/delete", methods=["POST"])
def delete_invoice(invoice_number: str):
    db.delete_invoice(invoice_number)
    flash(f"Invoice {invoice_number} deleted.", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
