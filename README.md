# GST Invoice Generator

A production-ready Python invoice generator for Indian GST billing. The project now includes a Bootstrap 5 web dashboard while preserving the original Tkinter desktop launcher and shared invoice, database and PDF services.

## Current Architecture

- `main.py` launches the original Tkinter application from `gst_invoice/main.py`.
- `app.py` provides the modern Flask + Bootstrap 5 web dashboard.
- `gst_invoice/models.py` contains dataclasses for company, customer, invoice and invoice items.
- `gst_invoice/invoice_generator.py` calculates taxable values, CGST, SGST, IGST and grand totals.
- `gst_invoice/pdf_generator.py` exports professional PDF invoices with ReportLab and a minimal fallback writer.
- `gst_invoice/database.py` persists company profiles, customers, invoices and invoice items in SQLite.
- `gst_invoice/validators.py` centralizes GSTIN, date, phone, email, GST rate and numeric validation.
- `templates/` contains the dashboard and invoice preview pages.
- `static/` contains custom styling and real-time invoice-calculation JavaScript.

## Improvement Opportunities Addressed

- Added a responsive Bootstrap 5 business UI with card sections, dashboard summary and invoice history.
- Added company branding fields including logo upload support.
- Added professional customer, invoice and editable product/service inputs.
- Added unlimited product rows with remove-row support and browser-side real-time totals.
- Added GST rate dropdowns for 0%, 5%, 12%, 18% and 28%.
- Centralized validation to prevent invalid GSTINs, dates, tax percentages, negative prices and invalid quantities.
- Added professional invoice preview with print and PDF download actions.
- Preserved the existing SQLite database, calculation engine and PDF generator.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the Web App

```bash
flask --app app run
```

Then open <http://127.0.0.1:5000>.

## Run the Desktop App

```bash
python main.py
```

## Create a Sample PDF

```bash
python scripts/create_sample_invoice.py
```

Generated PDFs are written under `gst_invoice/invoices/` and the SQLite database is created under `gst_invoice/database/`.
