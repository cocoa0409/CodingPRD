"""Frozen Novelty Plant API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.products import bp as products_bp
from routes.customers import bp as customers_bp
from routes.contracts import bp as contracts_bp
from routes.mix_batches import bp as mix_batches_bp
from routes.lines import bp as lines_bp
from routes.changeovers import bp as changeovers_bp
from routes.runs import bp as runs_bp
from routes.tunnels import bp as tunnels_bp
from routes.zones import bp as zones_bp
from routes.shipments import bp as shipments_bp
from routes.claims import bp as claims_bp
from routes.complaints import bp as complaints_bp
from routes.plans import bp as plans_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        products_bp,
        customers_bp,
        contracts_bp,
        mix_batches_bp,
        lines_bp,
        changeovers_bp,
        runs_bp,
        tunnels_bp,
        zones_bp,
        shipments_bp,
        claims_bp,
        complaints_bp,
        plans_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
