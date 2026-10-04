"""Entry point: Flask app, error handlers, route registration."""
from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error, success
from routes import abuse, agreements, billing, clock, models, organizations, payments, usage

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    import traceback
    traceback.print_exc()
    return error("ERR_INTERNAL", str(e), 500)


app.register_blueprint(clock.bp)
app.register_blueprint(organizations.bp)
app.register_blueprint(payments.bp)
app.register_blueprint(models.bp)
app.register_blueprint(usage.bp)
app.register_blueprint(billing.bp)
app.register_blueprint(agreements.bp)
app.register_blueprint(abuse.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
