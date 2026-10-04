"""Community Care Referral API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). Reads
PORT (default 10000), binds 0.0.0.0, runs in the foreground via start.sh.
"""
import os

from flask import Flask

import response
import routes_appointments
import routes_claims
import routes_network
import routes_platform
import routes_referrals
import routes_urgent_rx
import routes_veterans
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        routes_platform.bp,
        routes_network.bp,
        routes_veterans.bp,
        routes_referrals.bp,
        routes_appointments.bp,
        routes_claims.bp,
        routes_urgent_rx.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.err(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return response.err("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return response.err("ERR_INVALID_REQUEST", 400, "method not allowed on this path")

    @app.errorhandler(500)
    def handle_internal_error(err):
        return response.err("ERR_INVALID_REQUEST", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
