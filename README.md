# GST Invoice Generator

A production-ready Python 3.12+ Tkinter desktop application for generating Indian GST invoices with SQLite persistence and ReportLab PDF export.

## Features

- Company, customer, invoice and product-entry forms.
- Auto invoice numbers in `INV-YYYY-0001` format.
- Indian GST calculations: CGST + SGST for intra-state supply and IGST for inter-state supply.
- Professional GST PDF invoice with optional local logo, seller/buyer blocks, item table, tax summary, amount in words, terms and signature.
- SQLite tables: `company`, `customers`, `invoices`, `invoice_items`.
- Dashboard to create, search, export and delete invoices.
- Seed company: LaunchReadyCVs, GSTIN `29ABCDE1234F1Z5`, Bengaluru, Karnataka.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Project Structure

```text
gst_invoice/
├── main.py
├── database.py
├── models.py
├── invoice_generator.py
├── pdf_generator.py
├── utils.py
├── assets/
│   └── .gitkeep
├── database/
│   ├── .gitkeep
│   └── schema.sql
└── invoices/
```

## Sample PDF

Binary PDFs are generated locally and intentionally ignored by Git. After installing dependencies, run:

```bash
python scripts/create_sample_invoice.py
```

The command creates the SQLite database at `gst_invoice/database/gst_invoice.db` and writes a sample PDF under `gst_invoice/invoices/`.
