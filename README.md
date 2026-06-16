# Smart GST

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
- `DATABASE_URL` - SQLAlchemy database URL. Defaults to SQLite in `instance/`.
- `SESSION_COOKIE_SECURE` - set `true` behind HTTPS.
- `MAX_CONTENT_LENGTH` - max request/upload size in bytes.

## Deployment

Use `gunicorn app:app` (already defined in `Procfile`). Configure environment variables in Render, Railway, or AWS and mount persistent storage for `uploads/` if using SQLite/local PDF storage.
