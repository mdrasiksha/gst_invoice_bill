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
            self._migrate(conn)
            self.seed_company(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(company)")}
        for name in ("website", "bank_name", "account_number", "ifsc_code", "upi_id"):
            if name not in columns:
                conn.execute(f"ALTER TABLE company ADD COLUMN {name} TEXT DEFAULT ''")
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(customers)")}
        if "email" not in columns:
            conn.execute("ALTER TABLE customers ADD COLUMN email TEXT DEFAULT ''")
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(invoice_items)")}
        for name in ("discount_percentage", "discount_amount"):
            if name not in columns:
                conn.execute(f"ALTER TABLE invoice_items ADD COLUMN {name} REAL DEFAULT 0")
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
        for name in ("discount_total", "round_off"):
            if name not in columns:
                conn.execute(f"ALTER TABLE invoices ADD COLUMN {name} REAL DEFAULT 0")

    def seed_company(self, conn: sqlite3.Connection) -> None:
        exists = conn.execute("SELECT id FROM company LIMIT 1").fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO company (seller_name, gstin, address, phone, email, website, bank_name, account_number, ifsc_code, upi_id, state_code, logo_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("LaunchReadyCVs", "29ABCDE1234F1Z5", "Bengaluru, Karnataka", "+91 98765 43210", "billing@launchreadycvs.in", "www.launchreadycvs.in", "HDFC Bank", "1234567890", "HDFC0001234", "billing@upi", "29", ""),
            )

    def _company_from_row(self, row: sqlite3.Row) -> Company:
        return Company(id=row["id"], seller_name=row["seller_name"], gstin=row["gstin"], address=row["address"], phone=row["phone"] or "", email=row["email"] or "", website=row["website"] or "", bank_name=row["bank_name"] or "", account_number=row["account_number"] or "", ifsc_code=row["ifsc_code"] or "", upi_id=row["upi_id"] or "", state_code=row["state_code"] or "", logo_path=row["logo_path"] or "")

    def get_company(self) -> Company:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM company ORDER BY id LIMIT 1").fetchone()
        return self._company_from_row(row)

    def save_company(self, company: Company) -> int:
        company.state_code = company.state_code or state_code_from_gstin(company.gstin)
        values = (company.seller_name, company.gstin, company.address, company.phone, company.email, company.website, company.bank_name, company.account_number, company.ifsc_code, company.upi_id, company.state_code, company.logo_path)
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM company ORDER BY id LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE company SET seller_name=?, gstin=?, address=?, phone=?, email=?, website=?, bank_name=?, account_number=?, ifsc_code=?, upi_id=?, state_code=?, logo_path=? WHERE id=?", values + (row["id"],))
                return int(row["id"])
            cur = conn.execute("INSERT INTO company (seller_name, gstin, address, phone, email, website, bank_name, account_number, ifsc_code, upi_id, state_code, logo_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            return int(cur.lastrowid)

    def dashboard_stats(self) -> dict:
        month = date.today().strftime("%Y-%m")
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) n FROM invoices").fetchone()["n"]
            revenue = conn.execute("SELECT COALESCE(SUM(grand_total),0) n FROM invoices WHERE invoice_date LIKE ?", (month + "%",)).fetchone()["n"]
            customers = conn.execute("SELECT customer_name, MAX(id) id FROM customers GROUP BY customer_name ORDER BY id DESC LIMIT 5").fetchall()
        return {"total_invoices": total, "monthly_revenue": revenue, "recent_customers": customers}

    def next_invoice_number(self) -> str:
        year = date.today().year
        prefix = f"INV-{year}-"
        with self.connect() as conn:
            row = conn.execute("SELECT invoice_number FROM invoices WHERE invoice_number LIKE ? ORDER BY invoice_number DESC LIMIT 1", (prefix + "%",)).fetchone()
        number = int(row["invoice_number"].split("-")[-1]) + 1 if row else 1
        return f"{prefix}{number:04d}"

    def save_invoice(self, invoice: Invoice) -> int:
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO customers (customer_name, gstin, address, phone, email, state_code) VALUES (?, ?, ?, ?, ?, ?)", (invoice.customer.customer_name, invoice.customer.gstin, invoice.customer.address, invoice.customer.phone, invoice.customer.email, invoice.customer.state_code))
            customer_id = int(cur.lastrowid)
            cur = conn.execute("""INSERT INTO invoices (invoice_number, invoice_date, due_date, place_of_supply, state_code, company_id, customer_id, taxable_amount, discount_total, cgst, sgst, igst, round_off, grand_total, pdf_path)
                                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (invoice.invoice_number, invoice.invoice_date.isoformat(), invoice.due_date.isoformat(), invoice.place_of_supply, invoice.state_code, invoice.company.id, customer_id, invoice.taxable_amount, invoice.discount_total, invoice.cgst, invoice.sgst, invoice.igst, invoice.round_off, invoice.grand_total, invoice.pdf_path))
            invoice_id = int(cur.lastrowid)
            for item in invoice.items:
                conn.execute("""INSERT INTO invoice_items (invoice_id, item_name, hsn_sac, quantity, unit_price, gst_percentage, discount_percentage, discount_amount, taxable_value, gst_amount, total_amount)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (invoice_id, item.item_name, item.hsn_sac, item.quantity, item.unit_price, item.gst_percentage, item.discount_percentage, item.discount_amount, item.taxable_value, item.gst_amount, item.total_amount))
            return invoice_id

    def list_invoices(self, query: str = "") -> list[sqlite3.Row]:
        sql = """SELECT i.*, c.customer_name FROM invoices i JOIN customers c ON c.id = i.customer_id
                 WHERE (? = '' OR i.invoice_number LIKE ? OR c.customer_name LIKE ?) ORDER BY i.id DESC"""
        with self.connect() as conn:
            return list(conn.execute(sql, (query, f"%{query}%", f"%{query}%")))

    def list_customers(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM customers ORDER BY id DESC LIMIT 50"))

    def get_invoice(self, invoice_number: str) -> Invoice | None:
        with self.connect() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE invoice_number=?", (invoice_number,)).fetchone()
            if not inv:
                return None
            comp = conn.execute("SELECT * FROM company WHERE id=?", (inv["company_id"],)).fetchone()
            cust = conn.execute("SELECT * FROM customers WHERE id=?", (inv["customer_id"],)).fetchone()
            rows = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (inv["id"],)).fetchall()
        company = self._company_from_row(comp)
        customer = Customer(id=cust["id"], customer_name=cust["customer_name"], gstin=cust["gstin"] or "", address=cust["address"], phone=cust["phone"] or "", email=cust["email"] or "", state_code=cust["state_code"] or "")
        items = [InvoiceItem(id=r["id"], item_name=r["item_name"], hsn_sac=r["hsn_sac"], quantity=r["quantity"], unit_price=r["unit_price"], gst_percentage=r["gst_percentage"], discount_percentage=r["discount_percentage"] or 0, discount_amount=r["discount_amount"] or 0, taxable_value=r["taxable_value"], gst_amount=r["gst_amount"], total_amount=r["total_amount"]) for r in rows]
        return Invoice(id=inv["id"], invoice_number=inv["invoice_number"], invoice_date=date.fromisoformat(inv["invoice_date"]), due_date=date.fromisoformat(inv["due_date"]), place_of_supply=inv["place_of_supply"], state_code=inv["state_code"], company=company, customer=customer, items=items, taxable_amount=inv["taxable_amount"], discount_total=inv["discount_total"] or 0, cgst=inv["cgst"], sgst=inv["sgst"], igst=inv["igst"], round_off=inv["round_off"] or 0, grand_total=inv["grand_total"], pdf_path=inv["pdf_path"] or "")

    def delete_invoice(self, invoice_number: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM invoices WHERE invoice_number=?", (invoice_number,))


SCHEMA_SQL = Path(BASE_DIR / "database" / "schema.sql").read_text() if (BASE_DIR / "database" / "schema.sql").exists() else ""
