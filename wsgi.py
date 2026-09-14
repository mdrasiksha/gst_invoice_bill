"""WSGI entry point with legacy URL redirects and public SEO pages for GST Smart."""
from flask import redirect, render_template

from app import app


@app.route("/index.php")
def legacy_index():
    """Permanently redirect the legacy PHP-style homepage URL."""
    return redirect("/", code=301)


@app.route("/gst-invoice-generator")
def gst_invoice_generator():
    """Public SEO landing page for the GST invoice generator."""
    return render_template("gst_invoice_generator.html")
