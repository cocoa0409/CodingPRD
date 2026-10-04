"""Entry point: error handlers, route registration (INSTRUCTION.md contract)."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import appeals, catalog, commodities, incentives, orders, runs
from routes import shipments, trades

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (catalog, commodities, runs, orders, trades, appeals,
               incentives, shipments):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc: ApiError):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method(_exc):
    return error_response("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc: Exception):
    # Surface unexpected failures as a 400 validation envelope rather than a
    # bare HTML 500 so clients always get the standard error shape.
    return error_response("ERR_VALIDATION", 400, f"unexpected error: {exc}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
