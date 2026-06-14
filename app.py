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
from gst_invoice.validators import ALLOWED_GST_RATES, parse_gst_rate, parse_positive_float, parse_required_date, validate_company, validate_customer, validate_invoice_dates, validate_item

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


def company_from_form(form, files=None) -> Company:
    current = db.get_company()
    logo_path = (save_logo(files.get("company_logo")) if files else "") or form.get("existing_logo", current.logo_path).strip()
    gstin = form.get("company_gstin", "").strip().upper()
    return Company(
        seller_name=form.get("company_name", "").strip(), gstin=gstin, address=form.get("company_address", "").strip(), phone=form.get("company_phone", "").strip(), email=form.get("company_email", "").strip(), website=form.get("website", "").strip(), bank_name=form.get("bank_name", "").strip(), account_number=form.get("account_number", "").strip(), ifsc_code=form.get("ifsc_code", "").strip(), upi_id=form.get("upi_id", "").strip(), state_code=state_code_from_gstin(gstin) or current.state_code, logo_path=logo_path, id=current.id)


def build_invoice_from_form(form, files) -> Invoice:
    company = company_from_form(form, files)
    customer_gstin = form.get("customer_gstin", "").strip().upper()
    state_code = form.get("state_code", "").strip() or state_code_from_gstin(customer_gstin) or company.state_code
    customer = Customer(customer_name=form.get("customer_name", "").strip(), gstin=customer_gstin, address=form.get("customer_address", "").strip(), phone=form.get("customer_phone", "").strip(), email=form.get("customer_email", "").strip(), state_code=state_code)
    invoice_date = parse_required_date(form.get("invoice_date", ""), "Invoice date")
    due_date = parse_required_date(form.get("due_date", ""), "Due date")
    items: list[InvoiceItem] = []
    names = form.getlist("item_name[]")
    hsns = form.getlist("hsn_sac[]"); qtys = form.getlist("quantity[]"); rates = form.getlist("unit_price[]"); gsts = form.getlist("gst_percentage[]"); discounts = form.getlist("discount_percentage[]")
    for idx, name in enumerate(names):
        if not any((name, hsns[idx], qtys[idx], rates[idx])):
            continue
        item = InvoiceItem(item_name=name.strip(), hsn_sac=hsns[idx].strip(), quantity=parse_positive_float(qtys[idx], "Quantity"), unit_price=parse_positive_float(rates[idx], "Unit price", allow_zero=True), gst_percentage=parse_gst_rate(gsts[idx]), discount_percentage=parse_positive_float(discounts[idx] if idx < len(discounts) else "0", "Discount", allow_zero=True))
        validate_item(item)
        items.append(item)
    if not items:
        raise ValueError("Add at least one product or service row.")
    validate_company(company); validate_customer(customer); validate_invoice_dates(invoice_date, due_date)
    return calculate_invoice(Invoice(invoice_number=form.get("invoice_number", "").strip() or db.next_invoice_number(), invoice_date=invoice_date, due_date=due_date, place_of_supply=form.get("place_of_supply", "").strip() or "Karnataka", state_code=state_code, company=company, customer=customer, items=items))


@app.route("/")
def dashboard():
    return render_template("dashboard.html", company=db.get_company(), invoices=db.list_invoices(request.args.get("q", "")), stats=db.dashboard_stats())


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            company = company_from_form(request.form, request.files)
            validate_company(company)
            db.save_company(company)
            flash("Company settings saved for future invoices.", "success")
            return redirect(url_for("settings"))
        except Exception as exc:
            flash(str(exc), "danger")
    return render_template("settings.html", company=db.get_company())


@app.route("/invoice/new", methods=["GET", "POST"])
def create_invoice():
    if request.method == "POST":
        try:
            invoice = build_invoice_from_form(request.form, request.files)
            db.save_company(invoice.company)
            invoice.company = db.get_company()
            invoice.pdf_path = pdf.generate(invoice)
            db.save_invoice(invoice)
            flash(f"Invoice {invoice.invoice_number} saved successfully.", "success")
            return redirect(url_for("invoice_preview", invoice_number=invoice.invoice_number))
        except Exception as exc:
            flash(str(exc), "danger")
    defaults = {"invoice_number": db.next_invoice_number(), "invoice_date": date.today().isoformat(), "due_date": (date.today() + timedelta(days=15)).isoformat()}
    duplicate = db.get_invoice(request.args.get("duplicate", "")) if request.args.get("duplicate") else None
    return render_template("create_invoice.html", company=db.get_company(), customers=db.list_customers(), defaults=defaults, duplicate=duplicate, gst_rates=ALLOWED_GST_RATES, amount_to_words=amount_to_words)


@app.route("/invoice/<invoice_number>")
def invoice_preview(invoice_number: str):
    invoice = db.get_invoice(invoice_number)
    if not invoice:
        flash("Invoice not found.", "danger"); return redirect(url_for("dashboard"))
    return render_template("invoice_preview.html", invoice=invoice, amount_to_words=amount_to_words)


@app.route("/invoice/<invoice_number>/pdf")
def download_pdf(invoice_number: str):
    invoice = db.get_invoice(invoice_number)
    if not invoice:
        flash("Invoice not found.", "danger"); return redirect(url_for("dashboard"))
    path = Path(invoice.pdf_path) if invoice.pdf_path else Path(pdf.generate(invoice))
    if not path.exists(): path = Path(pdf.generate(invoice))
    return send_file(path, as_attachment=True, download_name=f"{invoice.invoice_number}.pdf")


@app.route("/invoice/<invoice_number>/delete", methods=["POST"])
def delete_invoice(invoice_number: str):
    db.delete_invoice(invoice_number); flash(f"Invoice {invoice_number} deleted.", "success"); return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
