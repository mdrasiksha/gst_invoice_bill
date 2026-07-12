"""Multi-tenant SaaS web application for GST invoice generation."""
from __future__ import annotations

import html, logging, os, secrets, smtplib, sys
from functools import wraps
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Flask, abort, flash, jsonify, make_response, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, text

from gst_invoice.favicon import ensure_favicon_assets
from gst_invoice.invoice_generator import calculate_invoice
from gst_invoice.invoice_data import build_invoice_data, company_detail_lines
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem, PasswordResetToken, ProductDescriptionSuggestion, User, db
from gst_invoice.pdf_generator import PDFGenerator
from gst_invoice.utils import INDIAN_STATE_CODES, amount_to_words, normalize_state_name, state_code_from_gstin, state_code_from_state, validate_email, validate_gstin, validate_phone
from gst_invoice.tax_service import DEFAULT_SUPPLIER_STATE
from gst_invoice.validators import ALLOWED_GST_RATES, parse_gst_rate, parse_positive_float, parse_required_date, validate_company, validate_customer, validate_invoice_dates, validate_item

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
    {"key": "free", "name": "Free", "price": "0", "limit": "50 invoices/month", "note": "Best for trying GST Smart."},
    {"key": "starter", "name": "Starter", "price": "199", "limit": "300 invoices/month", "note": "For growing invoice volume."},
    {"key": "pro", "name": "Pro", "price": "499", "limit": "Unlimited invoices", "note": "For regular business use."},
    {"key": "business", "name": "Business", "price": "999", "limit": "Unlimited invoices + future multi-user support", "note": "For teams preparing to scale."},
]
INVOICE_LIMIT_MESSAGE = "Monthly invoice limit reached. Please upgrade your plan to continue creating invoices."
GUEST_INVOICE_LIMIT = 3
GUEST_LIMIT_MESSAGE = "You have created 3 free invoices. Create a free account to continue generating invoices and save your invoice history."
PUBLIC_ENDPOINTS = {"landing", "about", "contact", "privacy_policy", "terms_and_conditions", "pricing", "robots_txt", "sitemap_xml", "favicon_asset"}


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
        SECRET_KEY=os.environ.get("SECRET_KEY", os.environ.get("GST_SMART_SECRET_KEY", os.environ.get("GST_INVOICE_SECRET_KEY", secrets.token_hex(32)))),
        SQLALCHEMY_DATABASE_URI=database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 2 * 1024 * 1024)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    ensure_favicon_assets(BASE_DIR / "static")
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
        if current_user.is_authenticated:
            ensure_user_company(current_user)

    @app.context_processor
    def inject_globals():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        def upload_exists(path_value: str) -> bool:
            if not path_value:
                return False
            path = Path(path_value)
            return (path if path.is_absolute() else BASE_DIR / path).exists()
        return {"csrf_token": session["csrf_token"], "upload_exists": upload_exists}

    @app.route("/robots.txt")
    def robots_txt():
        return send_from_directory(BASE_DIR, "robots.txt", mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        return send_from_directory(BASE_DIR, "sitemap.xml", mimetype="application/xml")

    @app.route("/favicon.ico")
    @app.route("/favicon-16x16.png")
    @app.route("/favicon-32x32.png")
    @app.route("/favicon-48x48.png")
    @app.route("/favicon-96x96.png")
    @app.route("/favicon-192x192.png")
    @app.route("/favicon-512x512.png")
    @app.route("/apple-touch-icon.png")
    @app.route("/android-chrome-192x192.png")
    @app.route("/android-chrome-512x512.png")
    @app.route("/site.webmanifest")
    def favicon_asset():
        filename = request.path.lstrip("/")
        mimetypes = {
            ".ico": "image/x-icon",
            ".png": "image/png",
            ".webmanifest": "application/manifest+json",
        }
        return send_from_directory(BASE_DIR / "static", filename, mimetype=mimetypes.get(Path(filename).suffix))

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
        add_column("password_reset_tokens", "used_at", "TIMESTAMP")
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




def normalize_description(value: str) -> str:
    """Normalize item descriptions so duplicate user suggestions are avoided."""
    return " ".join((value or "").strip().lower().split())


def suggestion_payload(suggestion: ProductDescriptionSuggestion) -> dict:
    """Return a browser-safe product/service suggestion payload."""
    return {
        "description": suggestion.description,
        "hsn_sac": suggestion.hsn_sac or "",
        "unit_price": suggestion.unit_price if suggestion.unit_price is not None else "",
        "gst_percentage": suggestion.gst_percentage if suggestion.gst_percentage is not None else "",
    }


def user_description_suggestions(user_id: int) -> list[dict]:
    """List saved product/service descriptions for the current user only."""
    suggestions = (
        ProductDescriptionSuggestion.query.filter_by(user_id=user_id)
        .order_by(ProductDescriptionSuggestion.usage_count.desc(), ProductDescriptionSuggestion.last_used_at.desc())
        .limit(200)
        .all()
    )
    return [suggestion_payload(item) for item in suggestions]


def remember_description_suggestions(user_id: int, items: list[InvoiceItem]) -> None:
    """Upsert product/service descriptions after an invoice is generated."""
    seen: set[str] = set()
    for item in items:
        normalized = normalize_description(item.item_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        suggestion = ProductDescriptionSuggestion.query.filter_by(user_id=user_id, normalized_description=normalized).first()
        if suggestion is None:
            suggestion = ProductDescriptionSuggestion(user_id=user_id, normalized_description=normalized)
        suggestion.description = item.item_name.strip()
        suggestion.hsn_sac = item.hsn_sac or ""
        suggestion.unit_price = item.unit_price
        suggestion.gst_percentage = item.gst_percentage
        suggestion.usage_count = (suggestion.usage_count or 0) + 1
        suggestion.last_used_at = datetime.utcnow()
        db.session.add(suggestion)

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

    company = Company(company_name="GST Smart Admin", gstin="", address="")
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



def build_new_invoice_customer(form) -> Customer:
    """Validate new-customer invoice fields separately from existing-customer lookup."""
    values = {
        "new_customer_name": form.get("new_customer_name", "").strip(),
        "new_customer_address": form.get("new_customer_address", "").strip(),
        "new_customer_city": form.get("new_customer_city", "").strip(),
        "new_customer_state": form.get("new_customer_state", "").strip(),
        "new_customer_pincode": form.get("new_customer_pincode", "").strip(),
    }
    if not values["new_customer_name"]:
        raise ValueError("Customer Name is required for a new customer.")

    gstin = form.get("new_customer_gstin", "").strip().upper()
    phone = form.get("new_customer_phone", "").strip()
    email = form.get("new_customer_email", "").strip()
    if not validate_gstin(gstin, optional=True):
        raise ValueError("Customer GSTIN is invalid.")
    if phone and not validate_phone(phone):
        raise ValueError("Customer phone number is invalid.")
    if email and not validate_email(email):
        raise ValueError("Customer email is invalid.")

    return Customer(
        company_id=(current_user.company_id if current_user.is_authenticated else None),
        customer_name=values["new_customer_name"],
        gstin=gstin,
        phone=phone,
        email=email,
        address=values["new_customer_address"],
        city=values["new_customer_city"],
        state=normalize_state_name(values["new_customer_state"]),
        pin_code=values["new_customer_pincode"],
        state_code=state_code_from_state(values["new_customer_state"]),
    )



def guest_invoice_count() -> int:
    return int(session.get("guest_invoice_count", 0) or 0)


def guest_invoices_remaining() -> int:
    return max(GUEST_INVOICE_LIMIT - guest_invoice_count(), 0)


def guest_limit_payload() -> dict:
    return {
        "ok": False,
        "message": GUEST_LIMIT_MESSAGE,
        "signup_url": url_for("register", next=url_for("create_invoice")),
        "login_url": url_for("login", next=url_for("create_invoice")),
    }


def build_guest_company(form) -> Company:
    state = normalize_state_name(form.get("company_state", "")) or DEFAULT_SUPPLIER_STATE
    company = Company(
        company_name=(form.get("company_name") or "Your Company").strip(),
        gstin=(form.get("company_gstin") or "").strip().upper(),
        address=(form.get("company_address") or "").strip(),
        city=(form.get("company_city") or "").strip(),
        state=state,
        pin_code=(form.get("company_pincode") or "").strip(),
        phone=(form.get("company_phone") or "").strip(),
        email=(form.get("company_email") or "").strip(),
        bank_name=(form.get("bank_name") or "").strip(),
        account_number=(form.get("account_number") or "").strip(),
        ifsc=(form.get("ifsc") or "").strip().upper(),
        upi_id=(form.get("upi_id") or "").strip(),
        authorized_signature_name=(form.get("authorized_signature_name") or "").strip(),
    )
    return company


def guest_default_company() -> Company:
    return Company(company_name="Your Company", gstin="", address="", city="", state=DEFAULT_SUPPLIER_STATE, pin_code="")

def friendly_invoice_error(exc: Exception) -> str:
    msg = str(exc) or "Server/database issue while generating the invoice."
    low = msg.lower()
    if "select a customer" in low or "customer selection" in low:
        return "Customer selection is required for an existing customer."
    if "item" in low or "product" in low or "service" in low or "quantity" in low or "unit price" in low:
        return "Missing invoice items. Please add at least one valid invoice item."
    if "gstin" in low or "gst number" in low or "gst rate" in low or "gst percentage" in low:
        return "Invalid GST number or GST rate. Please check the GST details."
    if "pdf" in low or exc.__class__.__name__.lower().endswith("pdferror"):
        return "PDF generation failed. Please try again or contact support."
    if exc.__class__.__name__ in {"IntegrityError", "OperationalError", "SQLAlchemyError"}:
        return "Server/database issue while generating the invoice. Please try again."
    return msg


def password_reset_link(token: str) -> str:
    base_url = (os.getenv("APP_URL") or request.url_root).rstrip("/")
    return f"{base_url}{url_for('reset_password')}?token={token}"


def reset_email_content(link: str) -> tuple[str, str]:
    safe_link = html.escape(link, quote=True)
    text = (
        "Hello,\n\n"
        "We received a request to reset your GST Smart password. Use the link below to set a new password:\n"
        f"{link}\n\n"
        "This link expires in 30 minutes. If you did not request a password reset, you can ignore this email.\n\n"
        "GST Smart Team"
    )
    html_body = f"""
    <p>Hello,</p>
    <p>We received a request to reset your GST Smart password.</p>
    <p><a href="{safe_link}" style="display:inline-block;padding:12px 18px;background:#0d6efd;color:#ffffff;text-decoration:none;border-radius:6px;">Reset your password</a></p>
    <p>If the button does not work, copy and paste this link into your browser:</p>
    <p><a href="{safe_link}">{safe_link}</a></p>
    <p>This link expires in 30 minutes.</p>
    <p>If you did not request a password reset, you can ignore this email.</p>
    <p>GST Smart Team</p>
    """.strip()
    return html_body, text


def send_reset_email(user: User, token: str) -> bool:
    link = password_reset_link(token)
    html_body, text_body = reset_email_content(link)
    resend_api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "noreply@gstsmart.com")
    sender = from_email if "<" in from_email else f"GST Smart <{from_email}>"
    reply_to = os.getenv("REPLY_TO_EMAIL", "gstsmartsupport@gmail.com")

    if resend_api_key:
        import requests

        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_api_key}", "Content-Type": "application/json"},
                json={
                    "from": sender,
                    "to": user.email,
                    "reply_to": reply_to,
                    "subject": "Reset your GST Smart password",
                    "html": html_body,
                    "text": text_body,
                },
                timeout=15,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("Failed to send password reset email through Resend: %s", exc, extra={"user_id": user.id})
            return False

    host = os.getenv("MAIL_SERVER") or os.getenv("SMTP_HOST")
    smtp_sender = os.getenv("MAIL_FROM") or os.getenv("SMTP_FROM") or sender
    if not host or not smtp_sender:
        logger.error("Password reset email provider is not configured", extra={"user_id": user.id})
        return False
    port = int(os.getenv("MAIL_PORT") or os.getenv("SMTP_PORT") or 587)
    username = os.getenv("MAIL_USERNAME") or os.getenv("SMTP_USERNAME")
    password = os.getenv("MAIL_PASSWORD") or os.getenv("SMTP_PASSWORD")
    use_tls = (os.getenv("MAIL_USE_TLS") or "true").lower() in {"1", "true", "yes", "on"}
    message = (
        f"Subject: Reset your GST Smart password\nTo: {user.email}\nFrom: {smtp_sender}\nReply-To: {reply_to}\n"
        f"Content-Type: text/plain; charset=utf-8\n\n{text_body}\n"
    )
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password or "")
            smtp.sendmail(smtp_sender, [user.email], message)
        return True
    except Exception:
        logger.exception("Failed to send password reset email through SMTP", extra={"user_id": user.id})
        return False


def update_company_from_form(company: Company):
    f = request.form
    company.company_name=f.get("company_name", "").strip(); company.gstin=f.get("gstin", "").strip().upper()
    company.address=f.get("address", "").strip(); company.city=f.get("city", "").strip(); company.state=normalize_state_name(f.get("state", "")); company.pin_code=f.get("pin_code", "").strip()
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
    validate_company(company)



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
    data = build_invoice_data(inv)
    data["amount_to_words"] = amount_to_words
    data["company_detail_lines"] = company_detail_lines(inv.company)
    return data


def log_invoice_tax_render_event(event: str, invoice_data: dict) -> None:
    logger.info(
        event,
        extra={
            "user_id": current_user.id if current_user.is_authenticated else None,
            "supplier_state": invoice_data.get("supplier_state"),
            "customer_state": invoice_data.get("customer_state"),
            "tax_type": invoice_data.get("tax_type"),
            "cgst_amount": invoice_data.get("cgst_amount"),
            "sgst_amount": invoice_data.get("sgst_amount"),
            "igst_amount": invoice_data.get("igst_amount"),
            "total_tax_amount": invoice_data.get("total_tax_amount"),
        },
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); password = request.form.get("password", "")
        if not email:
            flash("Email is required.", "danger"); return redirect(url_for("register"))
        if User.query.filter_by(email=email).first(): flash("Email already registered.", "danger"); return redirect(url_for("register"))
        if len(password) < 8: flash("Password must be at least 8 characters.", "danger"); return redirect(url_for("register"))
        company = Company(company_name=(request.form.get("company_name", "") or "").strip(), gstin="", address="")
        user = User(username=request.form.get("username", email).strip(), email=email, company=company); user.set_password(password)
        try:
            db.session.add_all([company, user]); db.session.commit()
        except IntegrityError:
            db.session.rollback(); flash("Email already registered.", "danger"); return redirect(url_for("register"))
        login_user(user); flash("Account created. Complete your company profile.", "success"); return redirect(safe_next_url("company_setup"))
    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    remembered_email = request.cookies.get("remembered_email", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            remember = bool(request.form.get("remember"))
            login_user(user, remember=remember)
            resp = make_response(redirect(safe_next_url("dashboard")))
            if remember:
                resp.set_cookie("remembered_email", email, max_age=60*60*24*365, httponly=True, samesite="Lax", secure=current_app_config_secure())
            else:
                resp.delete_cookie("remembered_email")
            return resp
        remembered_email = email or remembered_email
        flash("Invalid email or password", "danger")
    return render_template("auth/login.html", remembered_email=remembered_email)

@app.route("/logout", methods=["POST"])
@login_required
def logout(): logout_user(); flash("Logged out securely.", "success"); return redirect(url_for("login"))


def safe_next_url(default_endpoint: str) -> str:
    next_url = request.args.get("next", "")
    if next_url and urlsplit(next_url).netloc == "" and next_url.startswith("/"):
        return next_url
    return url_for(default_endpoint)

def current_app_config_secure() -> bool:
    return bool(app.config.get("SESSION_COOKIE_SECURE"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token_value = secrets.token_urlsafe(32)
            reset = PasswordResetToken(user_id=user.id, token=token_value, expires_at=datetime.utcnow() + timedelta(minutes=30))
            db.session.add(reset); db.session.commit()
            send_reset_email(user, token_value)
        flash("If an account exists with this email, password reset instructions have been sent.", "success")
    return render_template("auth/forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token=None):
    token = token or request.args.get("token", "")
    reset = PasswordResetToken.query.filter_by(token=token).first()
    if not reset or reset.used_at or reset.expires_at < datetime.utcnow():
        flash("Password reset link is invalid or expired.", "danger")
        return redirect(url_for("forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        else:
            reset.user.set_password(password); reset.used_at = datetime.utcnow(); db.session.commit()
            flash("Password updated. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("auth/reset_password.html")

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


@app.route("/pricing")
def pricing():
    current_plan = (getattr(current_user, "plan", "free") or "free") if current_user.is_authenticated else "free"
    return render_template("pricing.html", plans=PRICING_PLANS, current_plan=current_plan)


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/dashboard")
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
    company = ensure_user_company(current_user)
    if request.method == "POST":
        if request.form.get("action") == "skip":
            flash("No problem — you can update Company Settings anytime.", "success")
            return redirect(url_for("create_invoice"))
        try:
            update_company_from_form(company)
            db.session.commit()
            flash("Company settings saved. You can update them anytime.", "success")
            return redirect(url_for("create_invoice"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("settings.html", company=company, indian_states=INDIAN_STATE_CODES)

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
        customer.customer_name=request.form.get("customer_name","").strip(); customer.gstin=request.form.get("gstin","").strip().upper(); customer.address=request.form.get("address","").strip(); customer.city=request.form.get("city","").strip(); customer.state=normalize_state_name(request.form.get("state","")); customer.pin_code=request.form.get("pin_code","").strip(); customer.phone=request.form.get("phone","").strip(); customer.email=request.form.get("email","").strip(); customer.state_code=state_code_from_state(customer.state) or state_code_from_gstin(customer.gstin) or ""
        try: validate_customer(customer); db.session.add(customer); db.session.commit(); flash("Customer saved.", "success"); return redirect(url_for("customers"))
        except Exception as exc: db.session.rollback(); flash(str(exc), "danger")
    return render_template("customer_form.html", customer=customer, indian_states=INDIAN_STATE_CODES)

@app.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def customer_delete(customer_id):
    try:
        form_customer_id = request.form.get("customer_id", type=int) or customer_id
        if form_customer_id != customer_id:
            flash("Invalid customer delete request.", "warning")
            return redirect(url_for("customers"))
        customer = Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first()
        if not customer:
            flash("Customer not found or you do not have access to it.", "warning")
            return redirect(url_for("customers"))
        linked_invoices = Invoice.query.filter_by(company_id=current_user.company_id, customer_id=customer.id).all()
        for invoice in linked_invoices:
            db.session.delete(invoice)
        db.session.delete(customer)
        db.session.commit()
        flash("Customer deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Customer delete failed", extra={"user_id": current_user.id, "customer_id": customer_id})
        flash("Customer could not be deleted. Please try again or contact support.", "danger")
    return redirect(url_for("customers"))

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(BASE_DIR / "uploads", filename)

@app.route("/invoice/new", methods=["GET", "POST"])
def create_invoice():
    is_guest = not current_user.is_authenticated
    if request.method == "POST":
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")
        try:
            if is_guest and guest_invoice_count() >= GUEST_INVOICE_LIMIT:
                if wants_json:
                    return jsonify(guest_limit_payload()), 403
                flash(GUEST_LIMIT_MESSAGE, "warning")
                return redirect(url_for("create_invoice"))
            if not is_guest and invoice_limit_reached(current_user):
                if wants_json:
                    return jsonify({"ok": False, "message": INVOICE_LIMIT_MESSAGE}), 403
                flash(INVOICE_LIMIT_MESSAGE, "danger")
                return redirect(url_for("create_invoice"))

            company = build_guest_company(request.form) if is_guest else current_user.company
            customer_type = request.form.get("customer_type", "new")
            if customer_type == "new" or is_guest:
                customer = build_new_invoice_customer(request.form)
                if not is_guest and request.form.get("save_customer"):
                    db.session.add(customer)
            else:
                customer_id = request.form.get("customer_id", type=int)
                if not customer_id:
                    raise ValueError("Customer selection is required for an existing customer.")
                customer = Customer.query.filter_by(id=customer_id, company_id=current_user.company_id).first_or_404()
            customer_state = normalize_state_name(customer.state) or normalize_state_name(company.state)
            supply_code = state_code_from_state(customer_state) or (company.state_code or "").strip().zfill(2)
            # Treat the submitted state code as a helper/autofill value only.
            # A stale or manually mistyped code should not block invoice creation;
            # the authoritative code comes from the selected customer state.
            customer.state = customer_state
            customer.state_code = supply_code
            invoice_date = parse_required_date(request.form.get("invoice_date") or date.today().isoformat(), "Invoice date")
            due_date = parse_required_date(request.form.get("due_date") or invoice_date.isoformat(), "Due date")
            invoice_number = request.form.get("invoice_number") or (f"GUEST-{date.today():%Y%m%d}-{guest_invoice_count() + 1}" if is_guest else next_invoice_number(current_user.company_id))
            inv=Invoice(company=company, customer=customer, created_by_user_id=(None if is_guest else current_user.id), invoice_number=invoice_number, invoice_date=invoice_date, due_date=due_date, place_of_supply=customer_state, state_code=supply_code)
            setattr(inv, "terms", request.form.get("terms", "").strip())
            hsn_values=request.form.getlist("hsn_sac[]"); qty_values=request.form.getlist("quantity[]"); price_values=request.form.getlist("unit_price[]"); gst_values=request.form.getlist("gst_percentage[]")
            for idx,name in enumerate(request.form.getlist("item_name[]")):
                if not name.strip(): continue
                quantity = parse_positive_float(qty_values[idx], "Quantity") if idx < len(qty_values) and qty_values[idx].strip() else 1.0
                unit_price = parse_positive_float(price_values[idx], "Unit price", allow_zero=True) if idx < len(price_values) and price_values[idx].strip() else 0.0
                gst_percentage = parse_gst_rate(gst_values[idx]) if idx < len(gst_values) and gst_values[idx].strip() else 0.0
                item=InvoiceItem(item_name=name.strip(), hsn_sac=hsn_values[idx].strip() if idx < len(hsn_values) else "", quantity=quantity, unit_price=unit_price, gst_percentage=gst_percentage)
                validate_item(item); inv.items.append(item)
            if not inv.items: raise ValueError("Add at least one product or service row.")
            validate_invoice_dates(inv.invoice_date, inv.due_date); calculate_invoice(inv)
            if is_guest:
                invoice_data = build_invoice_data(inv)
                inv.pdf_path=pdf.generate(inv, invoice_data=invoice_data)
                session["guest_invoice_count"] = guest_invoice_count() + 1
                session["guest_pdf_path"] = inv.pdf_path
                session["guest_pdf_filename"] = f"{inv.invoice_number}.pdf"
                session.modified = True
                logger.info("Generated guest invoice PDF", extra={"invoice_number": inv.invoice_number, "pdf_path": inv.pdf_path})
                if wants_json:
                    return jsonify({"ok": True, "message": f"Invoice {inv.invoice_number} generated successfully.", "download_url": url_for("download_guest_pdf"), "filename": f"{inv.invoice_number}.pdf", "remaining": guest_invoices_remaining()})
                flash(f"Invoice generated. You have {guest_invoices_remaining()} free invoices remaining.", "success"); return redirect(url_for("download_guest_pdf"))
            db.session.add(inv); db.session.flush(); invoice_data = invoice_view_context(inv); inv.pdf_path=pdf.generate(inv, invoice_data=invoice_data); remember_description_suggestions(current_user.id, inv.items); db.session.commit(); logger.info("Generated invoice PDF", extra={"invoice_id": inv.id, "invoice_number": inv.invoice_number, "pdf_path": inv.pdf_path})
            if wants_json:
                return jsonify({"ok": True, "message": f"Invoice {inv.invoice_number} generated successfully.", "download_url": url_for("download_pdf", invoice_id=inv.id), "filename": f"{inv.invoice_number}.pdf"})
            flash(f"Invoice {inv.invoice_number} saved.", "success"); return redirect(url_for("download_pdf", invoice_id=inv.id))
        except Exception as exc:
            db.session.rollback(); logger.exception("Invoice generation failed", extra={"user_id": current_user.id if current_user.is_authenticated else None})
            message = friendly_invoice_error(exc)
            if wants_json:
                return jsonify({"ok": False, "message": message}), 400
            flash(message, "danger")
    if is_guest:
        defaults={"invoice_number":f"GUEST-{date.today():%Y%m%d}-{guest_invoice_count() + 1}","invoice_date":date.today().isoformat(),"due_date":(date.today()+timedelta(days=15)).isoformat()}
        default_supplier_state = DEFAULT_SUPPLIER_STATE
        default_supplier_state_code = (state_code_from_state(default_supplier_state) or "").strip().zfill(2)
        return render_template("create_invoice.html", company=guest_default_company(), customers=[], defaults=defaults, gst_rates=ALLOWED_GST_RATES, indian_states=INDIAN_STATE_CODES, description_suggestions=[], amount_to_words=amount_to_words, default_supplier_state_code=default_supplier_state_code, guest_remaining=guest_invoices_remaining(), guest_limit_message=GUEST_LIMIT_MESSAGE)
    defaults={"invoice_number":next_invoice_number(current_user.company_id),"invoice_date":date.today().isoformat(),"due_date":(date.today()+timedelta(days=15)).isoformat()}
    default_supplier_state = normalize_state_name(current_user.company.state) or DEFAULT_SUPPLIER_STATE
    default_supplier_state_code = (current_user.company.state_code or state_code_from_state(default_supplier_state) or state_code_from_state(DEFAULT_SUPPLIER_STATE) or "").strip().zfill(2)
    return render_template("create_invoice.html", company=current_user.company, customers=Customer.query.filter_by(company_id=current_user.company_id).order_by(Customer.customer_name.asc(), Customer.id.asc()).all(), defaults=defaults, gst_rates=ALLOWED_GST_RATES, indian_states=INDIAN_STATE_CODES, description_suggestions=user_description_suggestions(current_user.id), amount_to_words=amount_to_words, default_supplier_state_code=default_supplier_state_code, guest_remaining=None, guest_limit_message=GUEST_LIMIT_MESSAGE)

@app.route("/invoice/guest/pdf")
def download_guest_pdf():
    if current_user.is_authenticated:
        return redirect(url_for("create_invoice"))
    path_value = session.get("guest_pdf_path", "")
    if not path_value:
        flash("Generate an invoice PDF first.", "warning")
        return redirect(url_for("create_invoice"))
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        flash("Unable to download that invoice. Please generate it again.", "danger")
        return redirect(url_for("create_invoice"))
    return send_file(path, as_attachment=True, download_name=session.get("guest_pdf_filename", "invoice.pdf"))

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
    invoice_data = invoice_view_context(inv)
    log_invoice_tax_render_event("Rendering invoice preview with finalized tax data", invoice_data)
    return render_template("invoice_preview.html", **invoice_data)

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
    # Regenerate on each download so updated company assets/settings (logo, QR, signature) are reflected.
    invoice_data = invoice_view_context(inv)
    log_invoice_tax_render_event("Rendering invoice PDF download with finalized tax data", invoice_data)
    inv.pdf_path = pdf.generate(inv, invoice_data=invoice_data)
    db.session.commit()
    path = Path(inv.pdf_path)
    return send_file(path, as_attachment=True, download_name=f"{inv.invoice_number}.pdf")

@app.route("/invoice/<int:invoice_id>/delete", methods=["POST"])
@login_required
def delete_invoice(invoice_id):
    inv = scoped_invoice(invoice_id)
    if not inv:
        flash("Invoice not found or you do not have access to it.", "warning")
        return redirect(url_for("dashboard"))
    db.session.delete(inv); db.session.commit(); flash("Invoice deleted successfully.", "success"); return redirect(url_for("dashboard"))

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
