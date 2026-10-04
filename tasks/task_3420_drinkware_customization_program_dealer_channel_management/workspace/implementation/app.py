"""Entry point: Flask app wiring, envelope-shaped error handlers, and the
foreground server on 0.0.0.0:$PORT (default 10000)."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
import routes_allocations
import routes_applications
import routes_catalog
import routes_claims
import routes_clock
import routes_dealers
import routes_drops
import routes_enforcement
import routes_order_ops
import routes_orders
import routes_proofs
import routes_slots

app = Flask(__name__)

for module in (
    routes_clock, routes_dealers, routes_applications, routes_enforcement,
    routes_catalog, routes_drops, routes_allocations, routes_orders,
    routes_order_ops, routes_proofs, routes_slots, routes_claims,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", 500, "internal error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
