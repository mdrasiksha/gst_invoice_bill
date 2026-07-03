import io
import os
import sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timedelta

import pytest

from app import app, db, user_description_suggestions
from gst_invoice.models import Company, Customer, Invoice, InvoiceItem, PasswordResetToken, ProductDescriptionSuggestion, User
from gst_invoice.utils import INDIAN_STATE_CODES, state_code_from_state, state_name_from_code


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}", WTF_CSRF_ENABLED=False)
    # app already configured; rebuild schema on current engine for isolated tests
    with app.app_context():
        db.drop_all()
        db.create_all()
        company = Company(company_name="Acme", gstin="29ABCDE1234F1Z5", address="Addr", city="Bengaluru", state="KA", pin_code="560001", phone="9876543210")
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


def test_forgot_password_creates_token_and_hides_email_config_status(client, monkeypatch):
    monkeypatch.delenv('RESEND_API_KEY', raising=False)
    monkeypatch.delenv('MAIL_SERVER', raising=False); monkeypatch.delenv('SMTP_HOST', raising=False)
    rv = client.post('/forgot-password', data={"csrf_token": csrf(client), "email":"user@example.com"}, follow_redirects=True)
    assert b'If an account exists with this email, password reset instructions have been sent.' in rv.data
    assert b'Email service is not configured' not in rv.data
    with app.app_context():
        token = PasswordResetToken.query.one()
        assert datetime.utcnow() < token.expires_at <= datetime.utcnow() + timedelta(minutes=31)


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


def test_delete_customer_with_linked_invoices_deletes_customer_and_invoices(client):
    login(client)
    with app.app_context():
        inv = make_invoice(); cid = inv.customer_id; iid = inv.id
    rv = client.post(f'/customers/{cid}/delete', data={"csrf_token": csrf(client), "customer_id": cid}, follow_redirects=True)
    assert b'Customer deleted successfully.' in rv.data
    with app.app_context():
        assert db.session.get(Customer, cid) is None
        assert db.session.get(Invoice, iid) is None


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


def test_new_customer_invoice_validation_only_requires_name(client, caplog):
    login(client)
    data = invoice_post_data(new_customer_name="", new_customer_address="", new_customer_pincode="")
    data["csrf_token"] = csrf(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data=data)
    assert rv.status_code == 400
    assert "Customer Name" in rv.json["message"]
    assert "Customer Address" not in rv.json["message"]
    assert "Pincode" not in rv.json["message"]
    assert "Missing customer details" not in rv.json["message"]
    assert "Invoice generation failed" in caplog.text


def test_new_customer_invoice_allows_empty_pin_and_address_fields(client):
    login(client)
    data = invoice_post_data(
        invoice_number="INV-NO-PIN",
        new_customer_address="",
        new_customer_city="",
        new_customer_state="",
        new_customer_pincode="",
        state_code="29",
        place_of_supply="",
    )
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-NO-PIN").one()
        assert inv.customer.pin_code == ""
        assert inv.customer.address == ""
        assert inv.customer.state == "Karnataka"
        assert inv.state_code == "29"


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


def test_customers_page_shows_linked_invoice_details(client):
    login(client)
    with app.app_context():
        inv = make_invoice(); invoice_number = inv.invoice_number
    rv = client.get('/customers')
    assert invoice_number.encode() in rv.data
    assert b'22-06-2026' in rv.data
    assert '₹100.00'.encode() in rv.data
    assert b'Saved' in rv.data


def test_existing_customer_invoice_uses_selected_customer(client):
    login(client)
    with app.app_context():
        company = Company.query.first()
        first = Customer(company_id=company.id, customer_name="First Buyer", email="first@example.com", phone="1111111", gstin="", address="First Addr", city="Bengaluru", state="Karnataka", pin_code="111111", state_code="29")
        second = Customer(company_id=company.id, customer_name="Second Buyer", email="second@example.com", phone="2222222", gstin="", address="Second Addr", city="Chennai", state="Tamil Nadu", pin_code="222222", state_code="33")
        db.session.add_all([first, second]); db.session.commit(); second_id = second.id
    data = invoice_post_data(customer_type="existing", customer_id=str(second_id), invoice_number="INV-EXISTING-SELECTED", state_code="33")
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-EXISTING-SELECTED").one()
        assert inv.customer_id == second_id
        assert inv.customer.customer_name == "Second Buyer"
        assert inv.customer.email == "second@example.com"
        assert inv.customer.phone == "2222222"
        assert inv.customer.address == "Second Addr"
        assert inv.customer.state == "Tamil Nadu"
        assert inv.customer.pin_code == "222222"


@pytest.mark.parametrize("code,state", INDIAN_STATE_CODES.items())
def test_all_indian_state_mappings_are_bidirectional(code, state):
    assert state_code_from_state(state) == code
    assert state_name_from_code(code) == state


def test_create_invoice_autofills_state_code_place_and_uses_sgst_cgst_for_same_state(client):
    login(client)
    data = invoice_post_data(
        invoice_number="INV-STATE-SAME",
        new_customer_state="Karnataka",
        state_code="29",
        place_of_supply="Should be ignored",
    )
    data["gst_percentage[]"] = "18.0"
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-STATE-SAME").one()
        assert inv.state_code == "29"
        assert inv.place_of_supply == "Karnataka"
        assert inv.cgst == 9.0
        assert inv.sgst == 9.0
        assert inv.igst == 0.0


def test_create_invoice_autofills_state_code_place_and_uses_igst_for_different_state(client):
    login(client)
    data = invoice_post_data(invoice_number="INV-STATE-DIFF", new_customer_state="Tamil Nadu", state_code="33")
    data["gst_percentage[]"] = "18.0"
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-STATE-DIFF").one()
        assert inv.state_code == "33"
        assert inv.place_of_supply == "Tamil Nadu"
        assert inv.cgst == 0.0
        assert inv.sgst == 0.0
        assert inv.igst == 18.0


def test_create_invoice_ignores_state_code_mismatch_and_uses_customer_state(client):
    login(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={
        **invoice_post_data(invoice_number="INV-STATE-BAD", new_customer_state="Tamil Nadu", state_code="29"),
        "csrf_token": csrf(client),
    })
    assert rv.status_code == 200
    assert rv.json["ok"] is True
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-STATE-BAD").one()
        assert inv.state_code == "33"
        assert inv.place_of_supply == "Tamil Nadu"


def test_login_failed_password_keeps_entered_email(client):
    rv = client.post('/login', data={"csrf_token": csrf(client), "email": "user@example.com", "password": "wrong"})
    assert rv.status_code == 200
    assert b'value="user@example.com"' in rv.data


def test_admin_dashboard_shows_user_phone_numbers(client):
    login(client)
    with app.app_context():
        user = User.query.filter_by(email="user@example.com").one()
        user.is_admin = True
        db.session.commit()
    rv = client.get('/admin/dashboard')
    assert rv.status_code == 200
    assert b'<th>Phone</th>' in rv.data
    assert b'9876543210' in rv.data



def test_create_invoice_only_requires_customer_name_and_description(client):
    login(client)
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={
        **invoice_post_data(
            invoice_number="INV-MINIMUM-REQUIRED",
            new_customer_state="",
            state_code="",
            invoice_date="",
            due_date="",
            **{"quantity[]": "", "unit_price[]": ""},
        ),
        "csrf_token": csrf(client),
    })
    assert rv.status_code == 200
    assert rv.json["ok"] is True
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-MINIMUM-REQUIRED").one()
        assert inv.customer.customer_name == "Walk In Buyer"
        assert inv.items[0].item_name == "Service"
        assert inv.items[0].quantity == 1.0
        assert inv.items[0].unit_price == 0.0


def test_create_invoice_form_does_not_show_state_code_as_required_input(client):
    login(client)
    rv = client.get('/invoice/new')
    assert rv.status_code == 200
    assert b'State Code' not in rv.data
    assert b'name="state_code"' in rv.data

def test_description_suggestions_are_ranked_by_frequency_then_recency(client):
    login(client)
    with app.app_context():
        user = User.query.filter_by(email="user@example.com").one()
        db.session.add_all([
            ProductDescriptionSuggestion(user_id=user.id, description="Recent Low Use", normalized_description="recent low use", usage_count=1, last_used_at=datetime(2026, 6, 22, 12, 0, 0)),
            ProductDescriptionSuggestion(user_id=user.id, description="Older High Use", normalized_description="older high use", usage_count=4, last_used_at=datetime(2026, 6, 20, 12, 0, 0)),
            ProductDescriptionSuggestion(user_id=user.id, description="Newer High Use", normalized_description="newer high use", usage_count=4, last_used_at=datetime(2026, 6, 21, 12, 0, 0)),
        ])
        db.session.commit()
        suggestions = user_description_suggestions(user.id)
    assert [item["description"] for item in suggestions[:3]] == ["Newer High Use", "Older High Use", "Recent Low Use"]


def test_description_suggestion_dropdown_shows_only_descriptions_and_caps_at_five(client):
    login(client)
    rv = client.get('/static/js/invoice.js')
    js = rv.data.decode()
    assert '.slice(0,5)' in js
    assert '>${escapeHtml(item.description)}</button>' in js
    assert 'HSN/SAC ${item.hsn_sac}' not in js
    assert '${item.gst_percentage}% GST' not in js
    assert 'money(item.unit_price)' not in js
    assert "set('hsn_sac[]',suggestion.hsn_sac)" in js
    assert "set('unit_price[]',suggestion.unit_price)" in js
    assert "set('gst_percentage[]',suggestion.gst_percentage)" in js

def test_company_settings_allows_empty_save_and_redirects_to_invoice(client):
    login(client)
    rv = client.post('/settings', data={
        "csrf_token": csrf(client),
        "action": "save",
        "company_name": "",
        "gstin": "",
        "address": "",
        "city": "",
        "state": "",
        "pin_code": "",
        "phone": "",
        "email": "",
    }, follow_redirects=False)
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith('/invoice/new')
    with app.app_context():
        company = Company.query.first()
        assert company.company_name == ""
        assert company.gstin == ""
        assert company.address == ""


def test_company_settings_skip_redirects_to_invoice_without_validation(client):
    login(client)
    rv = client.post('/settings', data={"csrf_token": csrf(client), "action": "skip", "email": "not-an-email"}, follow_redirects=False)
    assert rv.status_code == 302
    assert rv.headers["Location"].endswith('/invoice/new')


def test_incomplete_company_is_not_forced_back_to_setup(client):
    login(client)
    with app.app_context():
        company = Company.query.first()
        company.company_name = ""
        company.gstin = ""
        company.address = ""
        company.city = ""
        company.state = ""
        company.pin_code = ""
        db.session.commit()
    rv = client.get('/invoice/new', follow_redirects=False)
    assert rv.status_code == 200
    assert b'Create Invoice' in rv.data


def test_optional_company_field_validation_is_specific(client):
    login(client)
    rv = client.post('/settings', data={"csrf_token": csrf(client), "action": "save", "email": "bad-email"}, follow_redirects=True)
    assert b'Please enter a valid email address, or leave it blank for now.' in rv.data
    assert b'Company name is required.' not in rv.data


def test_same_state_preview_and_pdf_use_same_cgst_sgst_tax_data(client, monkeypatch, caplog):
    caplog.set_level("INFO")
    login(client)
    import app as app_module
    captured = []

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(invoice_number="INV-PDF-SAME", new_customer_state="Karnataka", state_code="29", **{"gst_percentage[]": "18.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-PDF-SAME").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["tax_type"] == "CGST_SGST"
    assert preview_data["totals"]["cgst"] == 9.0
    assert preview_data["totals"]["sgst"] == 9.0
    assert preview_data["totals"]["igst"] == 0.0
    assert captured[-1]["tax_type"] == preview_data["tax_type"]
    assert captured[-1]["totals"] == preview_data["totals"]
    for key in ["taxable_amount", "tax_rate", "cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "grand_total"]:
        assert key in captured[-1]
    assert captured[-1]["cgst_amount"] == 9.0
    assert captured[-1]["sgst_amount"] == 9.0
    assert captured[-1]["total_tax_amount"] == 18.0
    assert "Finalized invoice tax breakdown" in caplog.text


def test_different_state_preview_and_pdf_use_same_igst_tax_data(client, monkeypatch, caplog):
    caplog.set_level("INFO")
    login(client)
    import app as app_module
    captured = []

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(invoice_number="INV-PDF-DIFF", new_customer_state="Tamil Nadu", state_code="33", **{"gst_percentage[]": "18.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-PDF-DIFF").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["tax_type"] == "IGST"
    assert preview_data["totals"]["cgst"] == 0.0
    assert preview_data["totals"]["sgst"] == 0.0
    assert preview_data["totals"]["igst"] == 18.0
    assert captured[-1]["tax_type"] == preview_data["tax_type"]
    assert captured[-1]["totals"] == preview_data["totals"]
    for key in ["taxable_amount", "tax_rate", "cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "grand_total"]:
        assert key in captured[-1]
    assert captured[-1]["igst_amount"] == 18.0
    assert captured[-1]["total_tax_amount"] == 18.0
    assert "Finalized invoice tax breakdown" in caplog.text


def test_no_gst_preview_and_pdf_use_zero_tax_data(client, monkeypatch, caplog):
    caplog.set_level("INFO")
    login(client)
    import app as app_module
    captured = []

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(invoice_number="INV-PDF-NOGST", new_customer_state="Karnataka", state_code="29", **{"gst_percentage[]": "0.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-PDF-NOGST").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["totals"]["cgst_amount"] == 0.0
    assert preview_data["totals"]["sgst_amount"] == 0.0
    assert preview_data["totals"]["igst_amount"] == 0.0
    assert preview_data["total_tax_amount"] == 0.0
    assert captured[-1]["totals"] == preview_data["totals"]
    assert captured[-1]["total_tax_amount"] == 0.0
    assert "Finalized invoice tax breakdown" in caplog.text


def test_new_user_no_company_settings_uses_shared_tax_data_for_preview_and_pdf(client, monkeypatch):
    login(client)
    import app as app_module
    captured = []
    with app.app_context():
        company = Company.query.first()
        company.gstin = ""
        company.state = ""
        db.session.commit()

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(invoice_number="INV-NEW-NO-SETTINGS", new_customer_state="Karnataka", state_code="29", **{"gst_percentage[]": "18.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-NEW-NO-SETTINGS").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["supplier_state"] == "Karnataka"
    assert preview_data["tax_type"] == "CGST_SGST"
    assert preview_data["cgst_amount"] == 9.0
    assert preview_data["sgst_amount"] == 9.0
    assert captured[-1]["totals"] == preview_data["totals"]


def test_new_user_with_company_settings_uses_shared_tax_data_for_preview_and_pdf(client, monkeypatch):
    login(client)
    import app as app_module
    captured = []

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(invoice_number="INV-NEW-WITH-SETTINGS", new_customer_state="Karnataka", state_code="29", **{"gst_percentage[]": "18.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-NEW-WITH-SETTINGS").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["supplier_state"] == "Karnataka"
    assert preview_data["tax_type"] == "CGST_SGST"
    assert captured[-1]["tax_type"] == preview_data["tax_type"]
    assert captured[-1]["grand_total"] == preview_data["grand_total"]


def test_existing_user_saved_company_settings_uses_shared_tax_data_for_preview_and_pdf(client, monkeypatch):
    login(client)
    import app as app_module
    captured = []
    with app.app_context():
        company = Company.query.first()
        customer = Customer(company_id=company.id, customer_name="Saved Buyer", address="Addr", city="Chennai", state="Tamil Nadu", state_code="33")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id

    def fake_generate(invoice, invoice_data=None):
        captured.append(invoice_data)
        return str(Path(app_module.BASE_DIR) / "uploads" / f"{invoice.invoice_number}.pdf")

    monkeypatch.setattr(app_module.pdf, "generate", fake_generate)
    data = invoice_post_data(customer_type="existing", customer_id=str(customer_id), invoice_number="INV-EXISTING-SETTINGS", state_code="33", **{"gst_percentage[]": "18.0"})
    rv = client.post('/invoice/new', headers={"X-Requested-With": "XMLHttpRequest"}, data={**data, "csrf_token": csrf(client)})
    assert rv.status_code == 200
    with app.app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-EXISTING-SETTINGS").one()
        preview_data = app_module.invoice_view_context(inv)
    assert preview_data["tax_type"] == "IGST"
    assert preview_data["igst_amount"] == 18.0
    assert preview_data["cgst_amount"] == 0.0
    assert preview_data["sgst_amount"] == 0.0
    assert captured[-1]["totals"] == preview_data["totals"]
