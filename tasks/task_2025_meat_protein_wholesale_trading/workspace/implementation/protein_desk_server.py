"""Protein Trading Desk API — entry point.

Flask app wiring: registers all route blueprints, converts ApiError into the
standard error envelope, and catches framework-level 404/405/500. All state
lives in process-memory dicts (see store.py); nothing is seeded at startup
and nothing touches disk.
"""

import os

from flask import Flask

from helpers import ApiError, error_response
import routes_reference
import routes_sheets
import routes_procurement
import routes_trading
import routes_logistics
import routes_claims
import routes_misc

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_reference, routes_sheets, routes_procurement,
               routes_trading, routes_logistics, routes_claims, routes_misc):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_exception(e):
    return error_response("ERR_INVALID_REQUEST", 500, f"Internal error: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
