"""Retail Cash Reload Network & Bank-as-a-Service Program Management API.

Entry point: registers every resource blueprint, installs the error handlers and
serves the app bound to 0.0.0.0 on $PORT.  The in-memory store starts empty and
nothing is ever seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes import (
    admin_clock,
    aml_alerts,
    bank_sponsors,
    brand_partners,
    card_accounts,
    disputes,
    float_windows,
    load_transactions,
    loss_allocations,
    programs,
    reload_locations,
    retailer_agreements,
    settlement_batches,
)

BLUEPRINTS = (
    admin_clock.bp,
    bank_sponsors.bp,
    programs.bp,
    brand_partners.bp,
    retailer_agreements.bp,
    reload_locations.bp,
    card_accounts.bp,
    load_transactions.bp,
    aml_alerts.bp,
    disputes.bp,
    loss_allocations.bp,
    settlement_batches.bp,
    float_windows.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_ENTITY_NOT_FOUND", "No route matches this request.", 404
            )
        if exc.code == 405:
            return response.error(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.", 400
            )
        if 400 <= exc.code < 500:
            return response.error(
                "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code
            )
        return response.error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)