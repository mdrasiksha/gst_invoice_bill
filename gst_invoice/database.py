"""SQLite persistence layer for the GST Invoice Generator."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import Company, Customer, Invoice, InvoiceItem
from .utils import state_code_from_gstin

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "gst_invoice.db"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self.seed_company(conn)

    def seed_company(self, conn: sqlite3.Connection) -> None:
        exists = conn.execute("SELECT id FROM company LIMIT 1").fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO company (seller_name, gstin, address, phone, email, state_code, logo_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("LaunchReadyCVs", "29ABCDE1234F1Z5", "Bengaluru, Karnataka", "+91 98765 43210", "billing@launchreadycvs.in", "29", ""),
            )

    def get_company(self) -> Company:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM company ORDER BY id LIMIT 1").fetchone()
        return Company(id=row["id"], seller_name=row["seller_name"], gstin=row["gstin"], address=row["address"], phone=row["phone"], email=row["email"], state_code=row["state_code"], logo_path=row["logo_path"])

    def save_company(self, company: Company) -> int:
        company.state_code = company.state_code or state_code_from_gstin(company.gstin)
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM company ORDER BY id LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE company SET seller_name=?, gstin=?, address=?, phone=?, email=?, state_code=?, logo_path=? WHERE id=?", (company.seller_name, company.gstin, company.address, company.phone, company.email, company.state_code, company.logo_path, row["id"]))
                return int(row["id"])
            cur = conn.execute("INSERT INTO company (seller_name, gstin, address, phone, email, state_code, logo_path) VALUES (?, ?, ?, ?, ?, ?, ?)", (company.seller_name, company.gstin, company.address, company.phone, company.email, company.state_code, company.logo_path))
            return int(cur.lastrowid)

    def next_invoice_number(self) -> str:
        year = date.today().year
        prefix = f"INV-{year}-"
        with self.connect() as conn:
            row = conn.execute("SELECT invoice_number FROM invoices WHERE invoice_number LIKE ? ORDER BY invoice_number DESC LIMIT 1", (prefix + "%",)).fetchone()
        number = int(row["invoice_number"].split("-")[-1]) + 1 if row else 1
        return f"{prefix}{number:04d}"

    def save_invoice(self, invoice: Invoice) -> int:
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO customers (customer_name, gstin, address, phone, state_code) VALUES (?, ?, ?, ?, ?)", (invoice.customer.customer_name, invoice.customer.gstin, invoice.customer.address, invoice.customer.phone, invoice.customer.state_code))
            customer_id = int(cur.lastrowid)
            cur = conn.execute("""INSERT INTO invoices (invoice_number, invoice_date, due_date, place_of_supply, state_code, company_id, customer_id, taxable_amount, cgst, sgst, igst, grand_total, pdf_path)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (invoice.invoice_number, invoice.invoice_date.isoformat(), invoice.due_date.isoformat(), invoice.place_of_supply, invoice.state_code, invoice.company.id, customer_id, invoice.taxable_amount, invoice.cgst, invoice.sgst, invoice.igst, invoice.grand_total, invoice.pdf_path))
            invoice_id = int(cur.lastrowid)
            for item in invoice.items:
                conn.execute("""INSERT INTO invoice_items (invoice_id, item_name, hsn_sac, quantity, unit_price, gst_percentage, taxable_value, gst_amount, total_amount)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (invoice_id, item.item_name, item.hsn_sac, item.quantity, item.unit_price, item.gst_percentage, item.taxable_value, item.gst_amount, item.total_amount))
            return invoice_id

    def list_invoices(self, query: str = "") -> list[sqlite3.Row]:
        sql = """SELECT i.*, c.customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id
                 WHERE (? = '' OR i.invoice_number LIKE ?) ORDER BY i.id DESC"""
        with self.connect() as conn:
            return list(conn.execute(sql, (query, f"%{query}%")))

    def get_invoice(self, invoice_number: str) -> Invoice | None:
        with self.connect() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE invoice_number=?", (invoice_number,)).fetchone()
            if not inv:
                return None
            comp = conn.execute("SELECT * FROM company WHERE id=?", (inv["company_id"],)).fetchone()
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (inv["customer_id"],)).fetchone()
            rows = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (inv["id"],)).fetchall()
        company = Company(id=comp["id"], seller_name=comp["seller_name"], gstin=comp["gstin"], address=comp["address"], phone=comp["phone"], email=comp["email"], state_code=comp["state_code"], logo_path=comp["logo_path"])
        customer = Customer(id=cust["id"], customer_name=cust["customer_name"], gstin=cust["gstin"], address=cust["address"], phone=cust["phone"], state_code=cust["state_code"])
        items = [InvoiceItem(id=r["id"], item_name=r["item_name"], hsn_sac=r["hsn_sac"], quantity=r["quantity"], unit_price=r["unit_price"], gst_percentage=r["gst_percentage"], taxable_value=r["taxable_value"], gst_amount=r["gst_amount"], total_amount=r["total_amount"]) for r in rows]
        return Invoice(id=inv["id"], invoice_number=inv["invoice_number"], invoice_date=date.fromisoformat(inv["invoice_date"]), due_date=date.fromisoformat(inv["due_date"]), place_of_supply=inv["place_of_supply"], state_code=inv["state_code"], company=company, customer=customer, items=items, taxable_amount=inv["taxable_amount"], cgst=inv["cgst"], sgst=inv["sgst"], igst=inv["igst"], grand_total=inv["grand_total"], pdf_path=inv["pdf_path"])

    def delete_invoice(self, invoice_number: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM invoices WHERE invoice_number=?", (invoice_number,))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS company (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name TEXT NOT NULL,
    gstin TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    state_code TEXT,
    logo_path TEXT
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    gstin TEXT,
    address TEXT NOT NULL,
    phone TEXT,
    state_code TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    place_of_supply TEXT NOT NULL,
    state_code TEXT NOT NULL,
    company_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    taxable_amount REAL NOT NULL,
    cgst REAL NOT NULL,
    sgst REAL NOT NULL,
    igst REAL NOT NULL,
    grand_total REAL NOT NULL,
    pdf_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(company_id) REFERENCES company(id),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    hsn_sac TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    gst_percentage REAL NOT NULL,
    taxable_value REAL NOT NULL,
    gst_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);
"""
