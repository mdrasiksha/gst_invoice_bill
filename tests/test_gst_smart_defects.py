import io
import os
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta

import pytest

from app import app, db
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem, PasswordResetToken, User


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}", WTF_CSRF_ENABLED=False)
    # app already configured; rebuild schema on current engine for isolated tests
    with app.app_context():
        db.drop_all()
        db.create_all()
        company = Company(company_name="Acme", gstin="29ABCDE1234F1Z5", address="Addr", city="Bengaluru", state="KA", pin_code="560001")
        user = User(username="u", email="user@example.com", company=company)
        user.set_password("password123")
        db.session.add_all([company, user])
        db.session.commit()
    yield app.test_client()


def csrf(c):
    with c.session_transaction() as s:
        return s.setdefault("csrf_token", "t")


def login(c, remember=False):
    c.get('/login')
    return c.post('/login', data={"csrf_token": csrf(c), "email": "user@example.com", "password": "password123", "remember": "on" if remember else ""}, follow_redirects=False)


def test_sign_name_has_no_hardcoded_default(client):
    login(client)
    rv = client.get('/settings')
    assert b'Mohamed Rasik' not in rv.data
    assert b'name="authorized_signature_name" value=""' in rv.data


def test_invoice_errors_are_friendly_and_logged(client, caplog):
    login(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={
        "csrf_token": csrf(client), "customer_type": "new", "new_customer_name": "", "invoice_date": "2026-06-22", "due_date": "2026-06-23"
    })
    assert rv.status_code == 400
    assert rv.json["message"].startswith("Customer Name")
    assert "Invoice generation failed" in caplog.text


def test_company_logo_persists_and_previews_after_login(client, tmp_path):
    login(client)
    buf = io.BytesIO(); Image.new('RGB', (1, 1), 'white').save(buf, format='PNG'); buf.seek(0); png = buf.getvalue()
    data = {"csrf_token": csrf(client), "company_name":"Acme", "gstin":"29ABCDE1234F1Z5", "address":"Addr", "city":"Bengaluru", "state":"KA", "pin_code":"560001", "logo": (io.BytesIO(png), "logo.png")}
    client.post('/settings', data=data, content_type='multipart/form-data')
    client.post('/logout', data={"csrf_token": csrf(client)})
    login(client)
    rv = client.get('/settings')
    assert b'Company logo preview' in rv.data
    assert b'uploads/company_logos/' in rv.data


def make_invoice():
    company = Company.query.first(); user = User.query.first()
    cust = Customer(company_id=company.id, customer_name="Buyer", gstin="", address="B addr")
    inv = Invoice(company=company, customer=cust, created_by_user_id=user.id, invoice_number="INV-2026-0001", invoice_date=datetime(2026,6,22).date(), due_date=datetime(2026,6,23).date(), state_code="29", taxable_amount=100, grand_total=100)
    inv.items.append(InvoiceItem(item_name="Service", quantity=1, unit_price=100, gst_percentage=0, taxable_value=100, gst_amount=0, total_amount=100))
    db.session.add_all([cust, inv]); db.session.commit(); return inv


def test_bill_to_highlight_and_empty_gst_hidden(client):
    login(client)
    with app.app_context(): inv = make_invoice(); iid = inv.id
    rv = client.get(f'/invoice/{iid}')
    assert b'bill-to-box' in rv.data
    assert b'GSTIN: Unregistered' not in rv.data


def test_delete_invoice_keeps_user_logged_in_and_flashes_success(client):
    login(client)
    with app.app_context(): inv = make_invoice(); iid = inv.id
    rv = client.post(f'/invoice/{iid}/delete', data={"csrf_token": csrf(client)}, follow_redirects=True)
    assert b'Invoice deleted successfully.' in rv.data
    assert b'GST Smart Dashboard' in rv.data


def test_remember_me_prefills_only_email(client):
    login(client, remember=True)
    client.post('/logout', data={"csrf_token": csrf(client)})
    rv = client.get('/login')
    assert b'value="user@example.com"' in rv.data
    assert b'password123' not in rv.data


def test_contact_email_updated(client):
    rv = client.get('/contact')
    assert b'gstsmartsupport@gmail.com' in rv.data


def test_forgot_password_creates_token_and_handles_missing_email_config(client, monkeypatch):
    monkeypatch.delenv('MAIL_SERVER', raising=False); monkeypatch.delenv('SMTP_HOST', raising=False)
    rv = client.post('/forgot-password', data={"csrf_token": csrf(client), "email":"user@example.com"}, follow_redirects=True)
    assert b'Email service is not configured' in rv.data
    with app.app_context():
        token = PasswordResetToken.query.one()
        assert token.expires_at > datetime.utcnow()


def test_reset_password_updates_password(client):
    with app.app_context():
        user = User.query.filter_by(email='user@example.com').one(); token = PasswordResetToken(user_id=user.id, token='abc', expires_at=datetime.utcnow()+timedelta(hours=1)); db.session.add(token); db.session.commit()
    rv = client.post('/reset-password/abc', data={"csrf_token": csrf(client), "password":"newpass123"}, follow_redirects=True)
    assert b'Password updated' in rv.data
    client.post('/login', data={"csrf_token": csrf(client), "email":"user@example.com", "password":"newpass123"})


def test_print_css_one_page_rules_present(client):
    rv = client.get('/static/css/app.css')
    assert b'@page{size:A4;margin:8mm}' in rv.data
    assert b'page-break' not in rv.data.lower()


def test_delete_customer_with_no_invoices(client):
    login(client)
    with app.app_context():
        company = Company.query.first()
        cust = Customer(company_id=company.id, customer_name="Delete Me", gstin="", address="Addr")
        db.session.add(cust); db.session.commit(); cid = cust.id
    rv = client.post(f'/customers/{cid}/delete', data={"csrf_token": csrf(client), "customer_id": cid}, follow_redirects=True)
    assert b'Customer deleted successfully.' in rv.data
    assert b'GST Smart Dashboard' not in rv.data
    with app.app_context():
        assert db.session.get(Customer, cid) is None


def test_delete_customer_with_linked_invoices_is_blocked(client):
    login(client)
    with app.app_context():
        inv = make_invoice(); cid = inv.customer_id
    rv = client.post(f'/customers/{cid}/delete', data={"csrf_token": csrf(client), "customer_id": cid}, follow_redirects=True)
    assert b'This customer has invoices linked. Please delete or reassign those invoices before deleting the customer.' in rv.data
    with app.app_context():
        assert db.session.get(Customer, cid) is not None


def test_delete_another_users_customer_is_blocked(client):
    login(client)
    with app.app_context():
        other_company = Company(company_name="Other", gstin="29ABCDE1234F1Z5", address="Addr", city="Mysuru", state="KA", pin_code="570001")
        other_user = User(username="other", email="other@example.com", company=other_company)
        other_user.set_password("password123")
        other_customer = Customer(company=other_company, customer_name="Other Buyer", gstin="", address="Addr")
        db.session.add_all([other_company, other_user, other_customer]); db.session.commit(); cid = other_customer.id
    rv = client.post(f'/customers/{cid}/delete', data={"csrf_token": csrf(client), "customer_id": cid}, follow_redirects=True)
    assert b'Customer not found or you do not have access to it.' in rv.data
    with app.app_context():
        assert db.session.get(Customer, cid) is not None


def test_delete_invalid_customer_id_shows_message(client):
    login(client)
    rv = client.post('/customers/999999/delete', data={"csrf_token": csrf(client), "customer_id": 999999}, follow_redirects=True)
    assert b'Customer not found or you do not have access to it.' in rv.data
    assert rv.status_code == 200


def invoice_post_data(**overrides):
    data = {
        "customer_type": "new",
        "new_customer_name": "Walk In Buyer",
        "new_customer_gstin": "",
        "new_customer_phone": "",
        "new_customer_email": "",
        "new_customer_address": "Buyer Street",
        "new_customer_city": "Bengaluru",
        "new_customer_state": "KA",
        "new_customer_pincode": "560001",
        "save_customer": "on",
        "invoice_number": "INV-TEST-001",
        "state_code": "29",
        "invoice_date": "2026-06-22",
        "due_date": "2026-06-23",
        "place_of_supply": "KA",
        "item_name[]": "Service",
        "hsn_sac[]": "9983",
        "quantity[]": "1",
        "unit_price[]": "100",
        "gst_percentage[]": "0.0",
    }
    data.update(overrides)
    return data


def test_new_customer_invoice_validation_is_field_specific(client, caplog):
    login(client)
    data = invoice_post_data(new_customer_name="", new_customer_address="")
    data["csrf_token"] = csrf(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data=data)
    assert rv.status_code == 400
    assert "Customer Name" in rv.json["message"]
    assert "Customer Address" in rv.json["message"]
    assert "Missing customer details" not in rv.json["message"]
    assert "Invoice generation failed" in caplog.text


def test_new_customer_without_gstin_generates_pdf_and_hides_gstin(client):
    login(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**invoice_post_data(), "csrf_token": csrf(client)})
    assert rv.status_code == 200
    assert rv.json["ok"] is True
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-TEST-001").one()
        invoice_id = inv.id
        assert inv.customer.gstin == ""
    preview = client.get(f'/invoice/{invoice_id}')
    assert b'GSTIN: Unregistered' not in preview.data
    customers_page = client.get('/customers')
    assert b'Walk In Buyer' in customers_page.data
    assert b'Unregistered' not in customers_page.data
    assert b'Not provided' not in customers_page.data
