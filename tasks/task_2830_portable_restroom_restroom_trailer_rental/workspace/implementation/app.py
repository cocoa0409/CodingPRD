"""Portable Restroom Rental API.

Flask entry point. Storage is in-memory and starts completely empty on every
boot: nothing is seeded, preloaded or hardcoded (see db.py).
"""
import os

from flask import Flask

from errors import ApiError
from responses import error
from routes.accounts import bp as accounts_bp
from routes.charges import bp as charges_bp
from routes.clock_api import bp as clock_bp
from routes.contracts import bp as contracts_bp
from routes.deployments import bp as deployments_bp
from routes.manifests import bp as manifests_bp
from routes.permits import bp as permits_bp
from routes.refdata import bp as refdata_bp
from routes.schedules import bp as schedules_bp
from routes.sites import bp as sites_bp
from routes.visits import bp as visits_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (accounts_bp, sites_bp, permits_bp, refdata_bp, contracts_bp,
                      deployments_bp, schedules_bp, visits_bp, manifests_bp,
                      charges_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error("ERR_INVALID_REQUEST",
                     "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
