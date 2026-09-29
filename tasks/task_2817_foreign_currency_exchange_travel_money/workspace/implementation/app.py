"""Retail FX & Travel Money API.

Storage is a plain in-memory dict tree that starts empty on every boot; nothing is
ever seeded, preloaded or persisted.  The harness relaunches this process before
every test, so a fresh boot must always be a fresh, empty network.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, error_response  # noqa: E402
from routes.buyback import bp as buyback_bp  # noqa: E402
from routes.customers import bp as customers_bp  # noqa: E402
from routes.inventory import bp as inventory_bp  # noqa: E402
from routes.notes import bp as notes_bp  # noqa: E402
from routes.rates import bp as rates_bp  # noqa: E402
from routes.reference import bp as reference_bp  # noqa: E402
from routes.shipments import bp as shipments_bp  # noqa: E402
from routes.transactions import bp as transactions_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in (
        reference_bp,
        rates_bp,
        inventory_bp,
        customers_bp,
        transactions_bp,
        buyback_bp,
        notes_bp,
        shipments_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 400
        if status == 404:
            return error_response("ERR_INVALID_REQUEST", "Resource not found.", 404)
        if status == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
        debug=False,
    )
