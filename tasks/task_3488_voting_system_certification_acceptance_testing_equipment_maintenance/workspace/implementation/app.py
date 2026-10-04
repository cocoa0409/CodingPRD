"""Application bootstrap: blueprint registration and error handlers.

The store (store.py) is in-memory and module-fresh on every boot; nothing is
seeded. The logical clock boots at 2026-09-01T00:00:00Z (store.BOOT_CLOCK).
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from domains import (
    audits,
    campaigns,
    certificates,
    clock,
    definitions,
    jurisdictions,
    labs,
    la_tests,
    modifications,
    officials,
    procurements,
    public_read,
    systems,
    units,
    work_orders,
)

BLUEPRINTS = [
    clock.bp,
    systems.bp,
    labs.bp,
    campaigns.bp,
    certificates.bp,
    jurisdictions.bp,
    officials.bp,
    procurements.bp,
    definitions.bp,
    la_tests.bp,
    units.bp,
    work_orders.bp,
    modifications.bp,
    audits.bp,
    public_read.bp,
]


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "path identifier does not resolve"))

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "path identifier does not resolve"))

    @app.errorhandler(500)
    def handle_internal_error(exc):
        return error_response(ApiError("ERR_INVALID_REQUEST", 500, "internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
