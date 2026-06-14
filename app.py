"""Multi-tenant SaaS web application for GST invoice generation."""
from __future__ import annotations

import logging, os, secrets
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from gst_invoice.invoice_generator import calculate_invoice
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem, User, db
from gst_invoice.pdf_generator import PDFGenerator
from gst_invoice.utils import amount_to_words, state_code_from_gstin
from gst_invoice.validators import ALLOWED_GST_RATES, parse_gst_rate, parse_positive_float, parse_required_date, validate_customer, validate_invoice_dates, validate_item

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "company_logos"
PDF_DIR = BASE_DIR / "uploads" / "invoices"
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", os.environ.get("GST_INVOICE_SECRET_KEY", secrets.token_hex(32))),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'gst_invoice_saas.db'}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 2 * 1024 * 1024)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True); PDF_DIR.mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager = LoginManager(app); login_manager.login_view = "login"; login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(user_id: str): return db.session.get(User, int(user_id))

    @app.before_request
    def protect_csrf_and_setup():
        if request.method == "POST":
            token = session.get("csrf_token")
            if not token or token != request.form.get("csrf_token"):
                abort(400, "Invalid CSRF token")
        if current_user.is_authenticated and request.endpoint not in {"logout", "company_setup", "static"}:
            if not current_user.company.profile_complete:
                return redirect(url_for("company_setup"))

    @app.context_processor
    def inject_globals():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return {"csrf_token": session["csrf_token"]}

    with app.app_context(): db.create_all()

    return app


app = create_app()
pdf = PDFGenerator(output_dir=PDF_DIR)
logger = logging.getLogger(__name__)


def save_logo(upload) -> str:
    if not upload or not upload.filename: return ""
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in ALLOWED_LOGO_EXTENSIONS: raise ValueError("Logo must be PNG, JPG, or JPEG.")
    filename = f"company-{current_user.company_id}-{secrets.token_hex(8)}{suffix}"
    target = UPLOAD_DIR / secure_filename(filename)
    upload.save(target)
    return str(target.relative_to(BASE_DIR))


def update_company_from_form(company: Company):
    f = request.form
    company.company_name=f.get("company_name", "").strip(); company.gstin=f.get("gstin", "").strip().upper()
    company.address=f.get("address", "").strip(); company.city=f.get("city", "").strip(); company.state=f.get("state", "").strip(); company.pin_code=f.get("pin_code", "").strip()
    company.phone=f.get("phone", "").strip(); company.email=f.get("email", "").strip(); company.website=f.get("website", "").strip()
    company.bank_name=f.get("bank_name", "").strip(); company.account_number=f.get("account_number", "").strip(); company.ifsc=f.get("ifsc", "").strip().upper(); company.upi_id=f.get("upi_id", "").strip()
    logo = save_logo(request.files.get("logo"));
    if logo: company.logo_path = logo
    if not company.company_name or not company.gstin or not company.address: raise ValueError("Company name, GSTIN and address are required.")


def next_invoice_number(company_id: int) -> str:
    year = date.today().year; prefix = f"INV-{year}-"
    last = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_number.like(prefix + "%")).order_by(Invoice.invoice_number.desc()).first()
    seq = int(last.invoice_number.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def scoped_invoice(invoice_id: int) -> Invoice:
    inv = Invoice.query.filter_by(id=invoice_id, company_id=current_user.company_id).first_or_404()
    return inv


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        if User.query.filter_by(email=email).first(): flash("Email already registered.", "danger"); return redirect(url_for("register"))
        if len(password) < 8: flash("Password must be at least 8 characters.", "danger"); return redirect(url_for("register"))
        company = Company(company_name=request.form.get("company_name", "New Company").strip() or "New Company", gstin="", address="")
        user = User(username=request.form.get("username", email).strip(), email=email, company=company); user.set_password(password)
        db.session.add_all([company, user]); db.session.commit(); login_user(user); flash("Account created. Complete your company profile.", "success"); return redirect(url_for("company_setup"))
    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember"))); return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout(): logout_user(); flash("Logged out securely.", "success"); return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST": flash("If the email exists, a reset link will be sent by the configured mail provider.", "info")
    return render_template("auth/forgot_password.html")

@app.route("/")
@login_required
def dashboard():
    cid=current_user.company_id
    today=date.today(); month_start=today.replace(day=1); next_month=(month_start.replace(year=month_start.year+1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month+1))
    monthly = Invoice.query.filter_by(company_id=cid).filter(Invoice.invoice_date >= month_start, Invoice.invoice_date < next_month).all()
    stats={"total_invoices":Invoice.query.filter_by(company_id=cid).count(),"monthly_revenue":sum(i.grand_total for i in monthly),"recent_customers":Customer.query.filter_by(company_id=cid).order_by(Customer.id.desc()).limit(5).all()}
    invoices=Invoice.query.filter_by(company_id=cid).order_by(Invoice.id.desc()).limit(20).all()
    return render_template("dashboard.html", company=current_user.company, invoices=invoices, stats=stats)

@app.route("/company/setup", methods=["GET", "POST"])
@app.route("/settings", methods=["GET", "POST"])
@login_required
def company_setup():
    if request.method == "POST":
        try: update_company_from_form(current_user.company); db.session.commit(); flash("Company profile saved.", "success"); return redirect(url_for("dashboard"))
        except Exception as exc: db.session.rollback(); flash(str(exc), "danger")
    return render_template("settings.html", company=current_user.company)

@app.route("/customers")
@login_required
def customers(): return render_template("customers.html", customers=Customer.query.filter_by(company_id=current_user.company_id).order_by(Customer.id.desc()).all())

@app.route("/customers/new", methods=["GET", "POST"])
@app.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@login_required
def customer_form(customer_id=None):
    customer = Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first() if customer_id else Customer(company_id=current_user.company_id)
    if customer_id and not customer: abort(404)
    if request.method == "POST":
        customer.customer_name=request.form.get("customer_name","").strip(); customer.gstin=request.form.get("gstin","").strip().upper(); customer.address=request.form.get("address","").strip(); customer.phone=request.form.get("phone","").strip(); customer.email=request.form.get("email","").strip(); customer.state_code=request.form.get("state_code","").strip() or state_code_from_gstin(customer.gstin) or ""
        try: validate_customer(customer); db.session.add(customer); db.session.commit(); flash("Customer saved.", "success"); return redirect(url_for("customers"))
        except Exception as exc: db.session.rollback(); flash(str(exc), "danger")
    return render_template("customer_form.html", customer=customer)

@app.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def customer_delete(customer_id):
    c=Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first_or_404(); db.session.delete(c); db.session.commit(); flash("Customer deleted.", "success"); return redirect(url_for("customers"))

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(BASE_DIR / "uploads", filename)

@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def create_invoice():
    if request.method == "POST":
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
        try:
            customer_id = request.form.get("customer_id", type=int)
            if not customer_id:
                raise ValueError("Select a customer before generating the PDF.")
            customer = Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first_or_404()
            inv=Invoice(company=current_user.company, customer=customer, invoice_number=request.form.get("invoice_number") or next_invoice_number(current_user.company_id), invoice_date=parse_required_date(request.form.get("invoice_date"),"Invoice date"), due_date=parse_required_date(request.form.get("due_date"),"Due date"), place_of_supply=request.form.get("place_of_supply","").strip(), state_code=request.form.get("state_code","").strip() or customer.state_code or current_user.company.state_code)
            setattr(inv, "terms", request.form.get("terms", "").strip())
            hsn_values=request.form.getlist("hsn_sac[]"); qty_values=request.form.getlist("quantity[]"); price_values=request.form.getlist("unit_price[]"); gst_values=request.form.getlist("gst_percentage[]"); discount_values=request.form.getlist("discount_percentage[]")
            for idx,name in enumerate(request.form.getlist("item_name[]")):
                if not name.strip(): continue
                item=InvoiceItem(item_name=name.strip(), hsn_sac=hsn_values[idx].strip(), quantity=parse_positive_float(qty_values[idx],"Quantity"), unit_price=parse_positive_float(price_values[idx],"Unit price",allow_zero=True), gst_percentage=parse_gst_rate(gst_values[idx]), discount_percentage=parse_positive_float(discount_values[idx],"Discount",allow_zero=True))
                validate_item(item); inv.items.append(item)
            if not inv.items: raise ValueError("Add at least one product or service row.")
            validate_invoice_dates(inv.invoice_date, inv.due_date); calculate_invoice(inv); db.session.add(inv); db.session.flush(); inv.pdf_path=pdf.generate(inv); db.session.commit(); logger.info("Generated invoice PDF", extra={"invoice_id": inv.id, "invoice_number": inv.invoice_number, "pdf_path": inv.pdf_path})
            if wants_json:
                return jsonify({"ok": True, "message": f"Invoice {inv.invoice_number} generated successfully.", "download_url": url_for("download_pdf", invoice_id=inv.id), "filename": f"{inv.invoice_number}.pdf"})
            flash(f"Invoice {inv.invoice_number} saved.", "success"); return redirect(url_for("download_pdf", invoice_id=inv.id))
        except Exception as exc:
            db.session.rollback(); logger.exception("Invoice PDF generation failed")
            if wants_json:
                return jsonify({"ok": False, "message": "We could not generate the PDF. Please check the invoice details and try again."}), 400
            flash(str(exc), "danger")
    defaults={"invoice_number":next_invoice_number(current_user.company_id),"invoice_date":date.today().isoformat(),"due_date":(date.today()+timedelta(days=15)).isoformat()}
    return render_template("create_invoice.html", company=current_user.company, customers=Customer.query.filter_by(company_id=current_user.company_id).all(), defaults=defaults, gst_rates=ALLOWED_GST_RATES)

@app.route("/invoice/<int:invoice_id>")
@login_required
def invoice_preview(invoice_id): return render_template("invoice_preview.html", invoice=scoped_invoice(invoice_id), amount_to_words=amount_to_words)

@app.route("/invoice/<int:invoice_id>/pdf")
@login_required
def download_pdf(invoice_id):
    inv=scoped_invoice(invoice_id); path=BASE_DIR / inv.pdf_path if inv.pdf_path else Path(pdf.generate(inv))
    if not path.exists(): path=Path(pdf.generate(inv))
    return send_file(path, as_attachment=True, download_name=f"{inv.invoice_number}.pdf")

@app.route("/invoice/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete_invoice(invoice_id): inv=scoped_invoice(invoice_id); db.session.delete(inv); db.session.commit(); flash("Invoice deleted.", "success"); return redirect(url_for("dashboard"))

if __name__ == "__main__": app.run(debug=True)
