"""Multi-tenant SaaS web application for GST invoice generation."""
from __future__ import annotations

import logging, os, secrets, sys
from functools import wraps
from datetime import date, datetime, timedelta
from pathlib import Path

import click
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, text

from gst_invoice.invoice_generator import calculate_invoice
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem, User, db
from gst_invoice.pdf_generator import PDFGenerator
from gst_invoice.utils import amount_to_words, state_code_from_gstin
from gst_invoice.validators import ALLOWED_GST_RATES, parse_gst_rate, parse_positive_float, parse_required_date, validate_customer, validate_invoice_dates, validate_item

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "company_logos"
QR_DIR = BASE_DIR / "uploads" / "upi_qr"
SIGNATURE_DIR = BASE_DIR / "uploads" / "signatures"
PDF_DIR = BASE_DIR / "uploads" / "invoices"
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_QR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_SIGNATURE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PLAN_MONTHLY_INVOICE_LIMITS = {"free": 50, "starter": 300, "pro": None, "business": None}
DEFAULT_ADMIN_EMAIL = "mototest2022@gmail.com"
DEFAULT_ADMIN_PASSWORD = "Moto@2020"
PRICING_PLANS = [
    {"key": "free", "name": "Free", "price": "0", "limit": "50 invoices/month", "note": "Best for trying Smart GST."},
    {"key": "starter", "name": "Starter", "price": "199", "limit": "300 invoices/month", "note": "For growing invoice volume."},
    {"key": "pro", "name": "Pro", "price": "499", "limit": "Unlimited invoices", "note": "For regular business use."},
    {"key": "business", "name": "Business", "price": "999", "limit": "Unlimited invoices + future multi-user support", "note": "For teams preparing to scale."},
]
INVOICE_LIMIT_MESSAGE = "Monthly invoice limit reached. Please upgrade your plan to continue creating invoices."
PUBLIC_ENDPOINTS = {"about", "contact", "privacy_policy", "terms_and_conditions", "pricing", "robots_txt", "sitemap_xml"}


def configure_logging(app: Flask) -> None:
    """Emit useful tracebacks in Render/Gunicorn production logs."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, stream=sys.stdout, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    app.logger.setLevel(level)


def default_company_for_user(user: User) -> Company:
    """Create safe placeholder company settings for legacy users missing a company."""
    name = (getattr(user, "username", "") or getattr(user, "email", "") or "New Company").strip()
    return Company(company_name=f"{name} Company", gstin="", address="", city="", state="", pin_code="")


def ensure_user_company(user: User) -> Company:
    """Guarantee the logged-in user has a company row before views access it."""
    company = getattr(user, "company", None)
    if company is not None:
        return company
    company = default_company_for_user(user)
    user.company = company
    db.session.add(company)
    db.session.add(user)
    db.session.commit()
    logger.warning("Created missing company settings for user", extra={"user_id": user.id})
    return company


def database_uri() -> str:
    """Return the production database URL, falling back to local SQLite.

    Render historically exposes PostgreSQL URLs with the ``postgres://``
    scheme, while SQLAlchemy expects ``postgresql://``. Normalize that
    value so the same DATABASE_URL can be used directly in production.
    """
    uri = (os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'instance' / 'gst_invoice_saas.db'}").strip()
    if uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    return uri


def create_app() -> Flask:
    app = Flask(__name__)
    configure_logging(app)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", os.environ.get("GST_INVOICE_SECRET_KEY", secrets.token_hex(32))),
        SQLALCHEMY_DATABASE_URI=database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 2 * 1024 * 1024)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True); QR_DIR.mkdir(parents=True, exist_ok=True); SIGNATURE_DIR.mkdir(parents=True, exist_ok=True); PDF_DIR.mkdir(parents=True, exist_ok=True)
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
        if current_user.is_authenticated and request.endpoint not in PUBLIC_ENDPOINTS | {"logout", "company_setup", "static", "uploaded_file", "admin_index", "admin_dashboard"}:
            company = ensure_user_company(current_user)
            if not company.profile_complete:
                return redirect(url_for("company_setup"))

    @app.context_processor
    def inject_globals():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return {"csrf_token": session["csrf_token"]}

    @app.cli.command("create-admin")
    @click.option("--email", required=True, help="Admin email address.")
    @click.option("--password", required=True, help="Admin password.")
    @click.option("--update-password", is_flag=True, help="Update the password if the admin user already exists.")
    def create_admin_command(email: str, password: str, update_password: bool) -> None:
        """Create or promote an admin user without deleting existing data."""
        user, created, password_updated = create_or_update_admin(email, password, update_existing_password=update_password)
        action = "Created" if created else "Updated"
        password_note = " Password updated." if password_updated else " Password unchanged."
        click.echo(f"{action} admin user {user.email}.{password_note}")

    with app.app_context():
        initialize_database()

    return app



def initialize_database() -> None:
    """Create missing tables and safe additive columns without deleting data."""
    db.create_all()
    ensure_database_columns()
    ensure_admin_user()


def ensure_database_columns() -> None:
    """Add backwards-compatible columns for existing SQLite/PostgreSQL databases."""
    dialect = db.engine.dialect.name
    with db.engine.begin() as conn:
        def columns(table: str) -> set[str]:
            if dialect == "sqlite":
                return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            rows = conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :table
                """),
                {"table": table},
            )
            return {row[0] for row in rows}

        def add_column(table: str, name: str, ddl: str) -> None:
            existing = columns(table)
            if name in existing:
                return
            if dialect == "postgresql":
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}")
            else:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

        add_column("users", "is_admin", "BOOLEAN NOT NULL DEFAULT FALSE" if dialect == "postgresql" else "INTEGER NOT NULL DEFAULT 0")
        add_column("users", "plan", "VARCHAR(20) NOT NULL DEFAULT 'free'")
        for name, ddl in {
            "city": "VARCHAR(80) DEFAULT ''",
            "state": "VARCHAR(80) DEFAULT ''",
            "pin_code": "VARCHAR(12) DEFAULT ''",
            "phone": "VARCHAR(30) DEFAULT ''",
            "email": "VARCHAR(180) DEFAULT ''",
            "website": "VARCHAR(180) DEFAULT ''",
            "logo_path": "VARCHAR(300) DEFAULT ''",
            "bank_name": "VARCHAR(120) DEFAULT ''",
            "account_number": "VARCHAR(60) DEFAULT ''",
            "ifsc": "VARCHAR(20) DEFAULT ''",
            "upi_id": "VARCHAR(120) DEFAULT ''",
            "qr_code_path": "VARCHAR(300) DEFAULT ''",
            "upi_qr_image_url": "VARCHAR(300) DEFAULT ''",
            "signature_image_path": "VARCHAR(300) DEFAULT ''",
            "authorized_signature_name": "VARCHAR(180) DEFAULT ''",
            "invoice_prefix": "VARCHAR(12) DEFAULT 'INV'",
        }.items():
            add_column("companies", name, ddl)
        refreshed_company_columns = columns("companies")
        if "qr_code_path" in refreshed_company_columns and "upi_qr_image_url" in refreshed_company_columns:
            conn.exec_driver_sql("UPDATE companies SET qr_code_path = upi_qr_image_url WHERE COALESCE(qr_code_path, '') = '' AND COALESCE(upi_qr_image_url, '') != ''")

        for name, ddl in {"city": "VARCHAR(80) DEFAULT ''", "state": "VARCHAR(80) DEFAULT ''", "pin_code": "VARCHAR(12) DEFAULT ''", "email": "VARCHAR(180) DEFAULT ''"}.items():
            add_column("customers", name, ddl)
        add_column("invoices", "round_off", "FLOAT DEFAULT 0")
        add_column("invoices", "created_by_user_id", "INTEGER")



def create_or_update_admin(email: str, password: str, *, update_existing_password: bool = False) -> tuple[User, bool, bool]:
    """Create a new admin or promote an existing user safely.

    Existing users keep all company/customer/invoice data. Their password is
    changed only when update_existing_password is explicitly enabled.
    """
    admin_email = (email or "").strip().lower()
    if not admin_email:
        raise click.ClickException("Admin email is required.")
    if not password:
        raise click.ClickException("Admin password is required.")

    user = User.query.filter_by(email=admin_email).first()
    password_updated = False
    if user:
        user.is_admin = True
        if update_existing_password and not user.check_password(password):
            user.set_password(password)
            password_updated = True
        db.session.add(user)
        db.session.commit()
        return user, False, password_updated

    company = Company(company_name="Smart GST Admin", gstin="", address="")
    user = User(username=admin_email.split("@", 1)[0] or "admin", email=admin_email, company=company, is_admin=True)
    user.set_password(password)
    db.session.add_all([company, user])
    db.session.commit()
    return user, True, True

def ensure_admin_user() -> None:
    """Optionally create the configured admin account once.

    ADMIN_EMAIL and ADMIN_PASSWORD may override the built-in bootstrap
    credentials. Existing users keep their company/customer/invoice data;
    ADMIN_UPDATE_PASSWORD controls whether their password is refreshed.
    """
    admin_email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL).strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    update_existing_password = os.getenv("ADMIN_UPDATE_PASSWORD", "true").lower() in {"1", "true", "yes", "on"}
    create_or_update_admin(admin_email, admin_password, update_existing_password=update_existing_password)
    logging.getLogger(__name__).info("Admin user configured: %s", admin_email)


app = create_app()
pdf = PDFGenerator(output_dir=PDF_DIR)
logger = logging.getLogger(__name__)


@app.errorhandler(Exception)
def log_unhandled_exception(exc):
    if getattr(exc, "code", None) is not None and getattr(exc, "code") < 500:
        return exc
    logger.exception("Unhandled application error", extra={"path": request.path, "endpoint": request.endpoint})
    return render_template("error.html"), 500


@app.errorhandler(404)
def not_found(_exc):
    return render_template("error.html", title="Not found", message="The requested record was not found or you do not have access to it."), 404



def admin_required(view_func):
    """Require an authenticated administrator for admin-only views."""
    @wraps(view_func)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped_view

def save_upload(upload, upload_dir: Path, allowed_extensions: set[str], label: str) -> str:
    if not upload or not upload.filename: return ""
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in allowed_extensions: raise ValueError(f"{label} must be PNG, JPG" + (", JPEG, or WEBP." if ".webp" in allowed_extensions else ", or JPEG."))
    try:
        Image.open(upload.stream).verify()
        upload.stream.seek(0)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"{label} must be a valid image file.") from exc
    filename = f"company-{current_user.company_id}-{secrets.token_hex(8)}{suffix}"
    target = upload_dir / secure_filename(filename)
    upload.save(target)
    return str(target.relative_to(BASE_DIR))

def save_logo(upload) -> str:
    return save_upload(upload, UPLOAD_DIR, ALLOWED_LOGO_EXTENSIONS, "Logo")

def save_upi_qr(upload) -> str:
    return save_upload(upload, QR_DIR, ALLOWED_QR_EXTENSIONS, "UPI QR image")

def save_signature(upload) -> str:
    return save_upload(upload, SIGNATURE_DIR, ALLOWED_SIGNATURE_EXTENSIONS, "E-sign image")


def update_company_from_form(company: Company):
    f = request.form
    company.company_name=f.get("company_name", "").strip(); company.gstin=f.get("gstin", "").strip().upper()
    company.address=f.get("address", "").strip(); company.city=f.get("city", "").strip(); company.state=f.get("state", "").strip(); company.pin_code=f.get("pin_code", "").strip()
    company.phone=f.get("phone", "").strip(); company.email=f.get("email", "").strip(); company.website=f.get("website", "").strip()
    company.bank_name=f.get("bank_name", "").strip(); company.account_number=f.get("account_number", "").strip(); company.ifsc=f.get("ifsc", "").strip().upper(); company.upi_id=f.get("upi_id", "").strip()
    company.authorized_signature_name=f.get("authorized_signature_name", "").strip()
    logo = save_logo(request.files.get("logo"));
    if logo: company.logo_path = logo
    qr = save_upi_qr(request.files.get("upi_qr_image"));
    if qr:
        company.qr_code_path = qr
        if hasattr(company, "upi_qr_image_url"):
            company.upi_qr_image_url = qr
    if f.get("remove_upi_qr") == "1":
        company.qr_code_path = ""
        if hasattr(company, "upi_qr_image_url"):
            company.upi_qr_image_url = ""
    signature = save_signature(request.files.get("signature_image"));
    if signature: company.signature_image_path = signature
    if f.get("remove_signature_image") == "1": company.signature_image_path = ""
    if not all([company.company_name, company.gstin, company.address, company.city, company.state, company.pin_code]):
        raise ValueError("Company name, GSTIN, address, city, state and PIN code are required.")



def current_month_bounds() -> tuple[datetime, datetime]:
    """Return UTC datetime bounds for the current calendar month."""
    today = date.today()
    month_start_date = today.replace(day=1)
    next_month_date = (
        month_start_date.replace(year=month_start_date.year + 1, month=1)
        if month_start_date.month == 12
        else month_start_date.replace(month=month_start_date.month + 1)
    )
    return datetime.combine(month_start_date, datetime.min.time()), datetime.combine(next_month_date, datetime.min.time())


def monthly_invoice_count(user: User) -> int:
    """Count invoices created by a user in the current calendar month."""
    month_start, next_month = current_month_bounds()
    return Invoice.query.filter(
        Invoice.created_by_user_id == user.id,
        Invoice.created_at >= month_start,
        Invoice.created_at < next_month,
    ).count()


def invoice_limit_for_user(user: User) -> int | None:
    """Return the monthly invoice limit for a user's plan, or None for unlimited."""
    if getattr(user, "is_admin", False):
        return None
    plan = (getattr(user, "plan", "free") or "free").lower()
    return PLAN_MONTHLY_INVOICE_LIMITS.get(plan, PLAN_MONTHLY_INVOICE_LIMITS["free"])


def invoice_limit_reached(user: User) -> bool:
    """Return True when the user's monthly invoice quota has been reached."""
    limit = invoice_limit_for_user(user)
    return limit is not None and monthly_invoice_count(user) >= limit

def next_invoice_number(company_id: int) -> str:
    year = date.today().year; prefix = f"INV-{year}-"
    last = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_number.like(prefix + "%")).order_by(Invoice.invoice_number.desc()).first()
    seq = int(last.invoice_number.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def scoped_invoice(invoice_id: int) -> Invoice | None:
    return Invoice.query.filter_by(id=invoice_id, company_id=current_user.company_id).first()


def invoice_view_context(inv: Invoice) -> dict:
    items = list(inv.items or [])
    max_gst_rate = max((float(item.gst_percentage or 0) for item in items), default=0.0)
    totals = {
        "taxable_amount": float(inv.taxable_amount or 0),
        "cgst": float(inv.cgst or 0),
        "sgst": float(inv.sgst or 0),
        "igst": float(inv.igst or 0),
        "round_off": float(inv.round_off or 0),
        "grand_total": float(inv.grand_total or 0),
        "max_gst_rate": max_gst_rate,
    }
    return {
        "invoice": inv,
        "customer": inv.customer,
        "company": inv.company,
        "invoice_items": items,
        "items": items,
        "totals": totals,
        "amount_to_words": amount_to_words,
    }


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        if not email:
            flash("Email is required.", "danger"); return redirect(url_for("register"))
        if User.query.filter_by(email=email).first(): flash("Email already registered.", "danger"); return redirect(url_for("register"))
        if len(password) < 8: flash("Password must be at least 8 characters.", "danger"); return redirect(url_for("register"))
        company = Company(company_name=request.form.get("company_name", "New Company").strip() or "New Company", gstin="", address="")
        user = User(username=request.form.get("username", email).strip(), email=email, company=company); user.set_password(password)
        try:
            db.session.add_all([company, user]); db.session.commit()
        except IntegrityError:
            db.session.rollback(); flash("Email already registered.", "danger"); return redirect(url_for("register"))
        login_user(user); flash("Account created. Complete your company profile.", "success"); return redirect(url_for("company_setup"))
    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember"))); return redirect(url_for("dashboard"))
        flash("Invalid email or password", "danger")
    return render_template("auth/login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout(): logout_user(); flash("Logged out securely.", "success"); return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST": flash("If the email exists, a reset link will be sent by the configured mail provider.", "info")
    return render_template("auth/forgot_password.html")

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")


@app.route("/terms-and-conditions")
def terms_and_conditions():
    return render_template("terms_and_conditions.html")


@app.route("/robots.txt")
def robots_txt():
    return send_from_directory(BASE_DIR, "robots.txt", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    return send_from_directory(BASE_DIR, "sitemap.xml", mimetype="application/xml")


@app.route("/pricing")
def pricing():
    current_plan = (getattr(current_user, "plan", "free") or "free") if current_user.is_authenticated else "free"
    return render_template("pricing.html", plans=PRICING_PLANS, current_plan=current_plan)


@app.route("/")
@login_required
def dashboard():
    company = ensure_user_company(current_user)
    cid=company.id
    today=date.today(); month_start=today.replace(day=1); next_month=(month_start.replace(year=month_start.year+1, month=1) if month_start.month == 12 else month_start.replace(month=month_start.month+1))
    monthly = Invoice.query.filter_by(company_id=cid).filter(Invoice.invoice_date >= month_start, Invoice.invoice_date < next_month).all()
    stats={"total_invoices":Invoice.query.filter_by(company_id=cid).count(),"monthly_revenue":sum(i.grand_total for i in monthly),"recent_customers":Customer.query.filter_by(company_id=cid).order_by(Customer.id.desc()).limit(5).all()}
    invoices=Invoice.query.filter_by(company_id=cid).order_by(Invoice.id.desc()).limit(20).all()
    return render_template("dashboard.html", company=company, invoices=invoices, stats=stats)

@app.route("/company/setup", methods=["GET", "POST"])
@app.route("/settings", methods=["GET", "POST"])
@login_required
def company_setup():
    if request.method == "POST":
        try: update_company_from_form(ensure_user_company(current_user)); db.session.commit(); flash("Company profile saved.", "success"); return redirect(url_for("dashboard"))
        except Exception as exc: db.session.rollback(); flash(str(exc), "danger")
    return render_template("settings.html", company=ensure_user_company(current_user))

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
        customer.customer_name=request.form.get("customer_name","").strip(); customer.gstin=request.form.get("gstin","").strip().upper(); customer.address=request.form.get("address","").strip(); customer.city=request.form.get("city","").strip(); customer.state=request.form.get("state","").strip(); customer.pin_code=request.form.get("pin_code","").strip(); customer.phone=request.form.get("phone","").strip(); customer.email=request.form.get("email","").strip(); customer.state_code=request.form.get("state_code","").strip() or state_code_from_gstin(customer.gstin) or ""
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
            if invoice_limit_reached(current_user):
                if wants_json:
                    return jsonify({"ok": False, "message": INVOICE_LIMIT_MESSAGE}), 403
                flash(INVOICE_LIMIT_MESSAGE, "danger")
                return redirect(url_for("create_invoice"))
            customer_type = request.form.get("customer_type", "new")
            if customer_type == "new":
                if not request.form.get("new_customer_name", "").strip():
                    raise ValueError("Customer Name is required for a new customer.")
                customer = Customer(
                    company_id=current_user.company_id,
                    customer_name=request.form.get("new_customer_name", "").strip(),
                    gstin=request.form.get("new_customer_gstin", "").strip().upper(),
                    phone=request.form.get("new_customer_phone", "").strip(),
                    email=request.form.get("new_customer_email", "").strip(),
                    address=request.form.get("new_customer_address", "").strip(),
                    city=request.form.get("new_customer_city", "").strip(),
                    state=request.form.get("new_customer_state", "").strip(),
                    pin_code=request.form.get("new_customer_pincode", "").strip(),
                )
                customer.state_code = state_code_from_gstin(customer.gstin) or request.form.get("state_code", "").strip() or current_user.company.state_code
                db.session.add(customer)
            else:
                customer_id = request.form.get("customer_id", type=int)
                if not customer_id:
                    raise ValueError("Select a customer before generating the PDF.")
                customer = Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first_or_404()
            inv=Invoice(company=current_user.company, customer=customer, created_by_user_id=current_user.id, invoice_number=request.form.get("invoice_number") or next_invoice_number(current_user.company_id), invoice_date=parse_required_date(request.form.get("invoice_date"),"Invoice date"), due_date=parse_required_date(request.form.get("due_date"),"Due date"), place_of_supply=request.form.get("place_of_supply","").strip(), state_code=request.form.get("state_code","").strip() or customer.state_code or current_user.company.state_code)
            setattr(inv, "terms", request.form.get("terms", "").strip())
            hsn_values=request.form.getlist("hsn_sac[]"); qty_values=request.form.getlist("quantity[]"); price_values=request.form.getlist("unit_price[]"); gst_values=request.form.getlist("gst_percentage[]")
            for idx,name in enumerate(request.form.getlist("item_name[]")):
                if not name.strip(): continue
                item=InvoiceItem(item_name=name.strip(), hsn_sac=hsn_values[idx].strip() if idx < len(hsn_values) else "", quantity=parse_positive_float(qty_values[idx],"Quantity"), unit_price=parse_positive_float(price_values[idx],"Unit price",allow_zero=True), gst_percentage=parse_gst_rate(gst_values[idx]))
                validate_item(item); inv.items.append(item)
            if not inv.items: raise ValueError("Add at least one product or service row.")
            validate_invoice_dates(inv.invoice_date, inv.due_date); calculate_invoice(inv); db.session.add(inv); db.session.flush(); inv.pdf_path=pdf.generate(inv); db.session.commit(); logger.info("Generated invoice PDF", extra={"invoice_id": inv.id, "invoice_number": inv.invoice_number, "pdf_path": inv.pdf_path})
            if wants_json:
                return jsonify({"ok": True, "message": f"Invoice {inv.invoice_number} generated successfully.", "download_url": url_for("download_pdf", invoice_id=inv.id), "filename": f"{inv.invoice_number}.pdf"})
            flash(f"Invoice {inv.invoice_number} saved.", "success"); return redirect(url_for("download_pdf", invoice_id=inv.id))
        except Exception as exc:
            db.session.rollback(); logger.exception("Invoice PDF generation failed")
            if wants_json:
                return jsonify({"ok": False, "message": str(exc)}), 400
            flash(str(exc), "danger")
    defaults={"invoice_number":next_invoice_number(current_user.company_id),"invoice_date":date.today().isoformat(),"due_date":(date.today()+timedelta(days=15)).isoformat()}
    return render_template("create_invoice.html", company=current_user.company, customers=Customer.query.filter_by(company_id=current_user.company_id).all(), defaults=defaults, gst_rates=ALLOWED_GST_RATES)

@app.route("/invoice/<int:invoice_id>")
@app.route("/invoice/view/<int:invoice_id>")
@login_required
def invoice_preview(invoice_id):
    inv = scoped_invoice(invoice_id)
    if not inv:
        flash("Invoice not found or you do not have access to it.", "warning")
        return redirect(url_for("dashboard"))
    if not inv.company or not inv.customer:
        logger.error("Invoice is missing related company/customer", extra={"invoice_id": invoice_id})
        abort(404)
    return render_template("invoice_preview.html", **invoice_view_context(inv))

@app.route("/invoice/<int:invoice_id>/pdf")
@login_required
def download_pdf(invoice_id):
    inv = scoped_invoice(invoice_id)
    if not inv:
        flash("Invoice not found or you do not have access to it.", "warning")
        return redirect(url_for("dashboard"))
    if not inv.company or not inv.customer:
        logger.error("Invoice PDF requested for incomplete invoice", extra={"invoice_id": invoice_id})
        abort(404)
    path = BASE_DIR / inv.pdf_path if inv.pdf_path else Path(pdf.generate(inv))
    if not path.exists():
        path = Path(pdf.generate(inv))
    return send_file(path, as_attachment=True, download_name=f"{inv.invoice_number}.pdf")

@app.route("/invoice/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    inv = scoped_invoice(invoice_id)
    if not inv:
        flash("Invoice not found or you do not have access to it.", "warning")
        return redirect(url_for("dashboard"))
    db.session.delete(inv); db.session.commit(); flash("Invoice deleted.", "success"); return redirect(url_for("dashboard"))

@app.route("/admin")
@admin_required
def admin_index():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    month_start, next_month = current_month_bounds()
    stats = {
        "users": User.query.count(),
        "companies": Company.query.count(),
        "invoices": Invoice.query.count(),
        "monthly_invoices": Invoice.query.filter(Invoice.created_at >= month_start, Invoice.created_at < next_month).count(),
    }
    latest_users = User.query.order_by(User.created_at.desc(), User.id.desc()).limit(10).all()
    latest_invoices = Invoice.query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(10).all()
    user_invoice_counts = (
        db.session.query(User, func.count(Invoice.id).label("invoice_count"))
        .outerjoin(Invoice, Invoice.created_by_user_id == User.id)
        .group_by(User.id)
        .order_by(func.count(Invoice.id).desc(), User.id.desc())
        .limit(20)
        .all()
    )
    company_invoice_counts = (
        db.session.query(Company, func.count(Invoice.id).label("invoice_count"))
        .outerjoin(Invoice, Invoice.company_id == Company.id)
        .group_by(Company.id)
        .order_by(func.count(Invoice.id).desc(), Company.id.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "admin_dashboard.html",
        stats=stats,
        latest_users=latest_users,
        latest_invoices=latest_invoices,
        user_invoice_counts=user_invoice_counts,
        company_invoice_counts=company_invoice_counts,
    )


if __name__ == "__main__": app.run(debug=True)
