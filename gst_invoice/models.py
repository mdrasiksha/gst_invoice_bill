"""SQLAlchemy models for the multi-tenant GST Invoice SaaS."""
from __future__ import annotations

from datetime import date, datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

from .utils import state_code_from_gstin


db = SQLAlchemy()


class Company(db.Model):
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(180), nullable=False)
    gstin = db.Column(db.String(15), nullable=False)
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(80), default="")
    state = db.Column(db.String(80), default="")
    pin_code = db.Column(db.String(12), default="")
    phone = db.Column(db.String(30), default="")
    email = db.Column(db.String(180), default="")
    website = db.Column(db.String(180), default="")
    logo_path = db.Column(db.String(300), default="")
    bank_name = db.Column(db.String(120), default="")
    account_number = db.Column(db.String(60), default="")
    ifsc = db.Column(db.String(20), default="")
    upi_id = db.Column(db.String(120), default="")
    invoice_prefix = db.Column(db.String(12), default="INV")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", back_populates="company", cascade="all, delete-orphan")
    customers = db.relationship("Customer", back_populates="company", cascade="all, delete-orphan")
    invoices = db.relationship("Invoice", back_populates="company", cascade="all, delete-orphan")

    @property
    def seller_name(self): return self.company_name
    @seller_name.setter
    def seller_name(self, value): self.company_name = value
    @property
    def state_code(self): return state_code_from_gstin(self.gstin) or ""
    @state_code.setter
    def state_code(self, _value): pass
    @property
    def ifsc_code(self): return self.ifsc
    @ifsc_code.setter
    def ifsc_code(self, value): self.ifsc = value
    @property
    def profile_complete(self): return bool(self.company_name and self.gstin and self.address and self.city and self.state and self.pin_code)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(180), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company = db.relationship("Company", back_populates="users")

    def set_password(self, password: str) -> None: self.password_hash = generate_password_hash(password)
    def check_password(self, password: str) -> bool: return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    customer_name = db.Column(db.String(180), nullable=False)
    gstin = db.Column(db.String(15), default="")
    address = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(30), default="")
    email = db.Column(db.String(180), default="")
    state_code = db.Column(db.String(2), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company = db.relationship("Company", back_populates="customers")
    invoices = db.relationship("Invoice", back_populates="customer")


class Invoice(db.Model):
    __tablename__ = "invoices"
    __table_args__ = (db.UniqueConstraint("company_id", "invoice_number", name="uq_company_invoice_number"),)
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    invoice_number = db.Column(db.String(40), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False, default=date.today)
    place_of_supply = db.Column(db.String(120), default="")
    state_code = db.Column(db.String(2), default="")
    taxable_amount = db.Column(db.Float, default=0)
    discount_total = db.Column(db.Float, default=0)
    cgst = db.Column(db.Float, default=0)
    sgst = db.Column(db.Float, default=0)
    igst = db.Column(db.Float, default=0)
    round_off = db.Column(db.Float, default=0)
    grand_total = db.Column(db.Float, default=0)
    pdf_path = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    company = db.relationship("Company", back_populates="invoices")
    customer = db.relationship("Customer", back_populates="invoices")
    items = db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    @property
    def is_intrastate(self): return (self.company.state_code or "") == (self.state_code or "")


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    item_name = db.Column(db.String(240), nullable=False)
    hsn_sac = db.Column(db.String(30), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    gst_percentage = db.Column(db.Float, nullable=False)
    discount_percentage = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    taxable_value = db.Column(db.Float, default=0)
    gst_amount = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    invoice = db.relationship("Invoice", back_populates="items")
    def calculate(self):
        gross = round(self.quantity * self.unit_price, 2)
        self.discount_amount = round(gross * self.discount_percentage / 100, 2)
        self.taxable_value = round(gross - self.discount_amount, 2)
        self.gst_amount = round(self.taxable_value * self.gst_percentage / 100, 2)
        self.total_amount = round(self.taxable_value + self.gst_amount, 2)
