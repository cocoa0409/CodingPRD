"""Entry point: Flask app wiring, error handlers, route registration."""
import os
from flask import Flask
from errors import ApiError, err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

app = Flask(__name__)

from routes import core, funds, catalog, loans, holds, orders, invoices, events, snapshots, ops

for module in (core, funds, catalog, loans, holds, orders, invoices, events, snapshots, ops):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err(ERR_NOT_FOUND, "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err(ERR_NOT_FOUND, "method not allowed"))


@app.errorhandler(400)
def handle_400(e):
    return error_response(err(ERR_INVALID_REQUEST, "malformed request"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    import traceback
    traceback.print_exc()
    return error_response(err(ERR_INVALID_REQUEST, f"unexpected error: {e}"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
