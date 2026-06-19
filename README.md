# GST Smart

A multi-tenant Flask SaaS application for Indian GST invoicing. Multiple companies can register, complete an isolated company profile, manage their own customers, generate independently numbered invoices, and download branded ReportLab PDFs.

## Architecture

`User -> Company -> Customers/Invoices/InvoiceItems`

- One company has many users, customers, and invoices.
- All dashboard, customer, invoice, PDF, and delete routes scope queries by `current_user.company_id`.
- Passwords are hashed with Werkzeug and sessions are managed by Flask-Login.
- CSRF tokens are validated on every POST.
- Logo uploads are restricted to PNG/JPG/JPEG under `uploads/company_logos/` with a configurable max request size.

## Project Structure

- `app.py` - Flask SaaS app, authentication, company wizard, customers, invoices, tenant scoping.
- `gst_invoice/models.py` - SQLAlchemy models for Users, Companies, Customers, Invoices, InvoiceItems.
- `gst_invoice/invoice_generator.py` - GST calculation engine preserved from the original project.
- `gst_invoice/pdf_generator.py` - ReportLab PDF generation with company-specific branding.
- `templates/` - Bootstrap 5 SaaS UI.
- `static/js/invoice.js` - live invoice preview and browser-side calculations.
- `uploads/company_logos/` - runtime company logos.
- `uploads/invoices/` - generated PDF invoices.
- `Procfile`, `.env.example`, `requirements.txt` - deployment readiness for Render, Railway, and AWS.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app run
```

Open <http://127.0.0.1:5000>, register a company account, complete the company profile, add customers, and create invoices.

## Environment Variables

- `SECRET_KEY` - Flask secret key.
- `DATABASE_URL` - SQLAlchemy database URL. If set to a non-empty value, the app uses it (including Render PostgreSQL); otherwise it defaults to local SQLite in `instance/`.
- `SESSION_COOKIE_SECURE` - set `true` behind HTTPS.
- `MAX_CONTENT_LENGTH` - max request/upload size in bytes.
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` - optional one-time admin bootstrap credentials. If the email already exists, the user is left unchanged.
- `ADMIN_USERNAME` / `ADMIN_COMPANY_NAME` - optional labels for the one-time admin bootstrap user and company.

## Deployment

Use `gunicorn app:app` (already defined in `Procfile`). Configure environment variables in Render, Railway, or AWS and mount persistent storage for `uploads/` if generated PDFs and uploaded logos/QR codes must survive redeploys.

### Render PostgreSQL setup

1. Create a Render PostgreSQL database from the Render dashboard.
2. Copy the database **Internal Database URL**. Render may show a URL that starts with `postgres://`; the app normalizes it to SQLAlchemy-compatible `postgresql://` automatically.
3. In the Render web service, add an environment variable named `DATABASE_URL` with that PostgreSQL URL.
4. Redeploy the service. On startup, the app runs `db.create_all()` inside the Flask app context to create missing tables without dropping tables or deleting users, customers, invoices, or company settings.
5. Do not set `DATABASE_URL` for local development unless you want to use PostgreSQL locally; without it, the app uses SQLite at `instance/gst_invoice_saas.db`.
6. Optional: set `ADMIN_EMAIL` and `ADMIN_PASSWORD` once to bootstrap an admin login. If that email already exists, startup leaves the account and password unchanged.
