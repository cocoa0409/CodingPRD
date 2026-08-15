"""Electronic Component Distribution API — Flask entry point."""

import os

from flask import Flask

import errors as E
from errors import ApiError
from response import error as error_response

from routes import allocations, alternates, buybacks, catalog, claims, clock as clock_routes, customers, lots, orders, registrations

app = Flask(__name__)

app.register_blueprint(clock_routes.bp)
app.register_blueprint(catalog.bp)
app.register_blueprint(customers.bp)
app.register_blueprint(registrations.bp)
app.register_blueprint(orders.bp)
app.register_blueprint(alternates.bp)
app.register_blueprint(lots.bp)
app.register_blueprint(allocations.bp)
app.register_blueprint(claims.bp)
app.register_blueprint(buybacks.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc: ApiError):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response(E.ERR_INVALID_REQUEST, str(exc), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
