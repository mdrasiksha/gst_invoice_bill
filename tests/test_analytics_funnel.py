import sys
from pathlib import Path
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, db, build_funnel_report
from gst_invoice.models import AnalyticsEvent, Company, User


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test.db"
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}")
    with app.app_context():
        db.drop_all(); db.create_all()
        company = Company(company_name="Acme", gstin="29ABCDE1234F1Z5", address="Addr")
        user = User(username="u", email="user@example.com", company=company)
        user.set_password("password123")
        db.session.add_all([company, user]); db.session.commit()
    yield app.test_client()


def csrf(c):
    with c.session_transaction() as s:
        return s.setdefault("csrf_token", "t")


def test_homepage_landing_event_dedupes_per_session_per_day(client):
    client.get("/")
    client.get("/")
    with app.app_context():
        assert AnalyticsEvent.query.filter_by(event_name="landing_page_viewed").count() == 1


def test_create_invoice_click_endpoint_records_once(client):
    rv = client.post("/analytics/create-invoice-click", data={"csrf_token": csrf(client)}, follow_redirects=False)
    assert rv.status_code == 302
    with app.app_context():
        assert AnalyticsEvent.query.filter_by(event_name="create_invoice_clicked").count() == 1


def test_admin_funnel_requires_admin(client):
    client.post('/login', data={"csrf_token": csrf(client), "email":"user@example.com", "password":"password123"})
    rv = client.get('/admin/dashboard')
    assert rv.status_code == 403


def test_funnel_report_counts_date_range(client):
    client.get("/")
    with app.app_context():
        db.session.add(AnalyticsEvent(event_name="landing_page_viewed", session_id="old", guest_id="old", event_date=date.today() - timedelta(days=40)))
        db.session.commit()
        report = build_funnel_report(date.today() - timedelta(days=1), date.today())
        assert report["stages"][0]["count"] == 1
