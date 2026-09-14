"""WSGI entry point with legacy URL redirects for GST Smart."""
from flask import redirect

from app import app


@app.route("/index.php")
def legacy_index():
    """Permanently redirect the legacy PHP-style homepage URL."""
    return redirect("/", code=301)
