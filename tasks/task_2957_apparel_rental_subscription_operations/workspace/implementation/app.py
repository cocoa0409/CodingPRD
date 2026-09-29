"""Apparel Rental Subscription Operations API — entry point.

In-memory only: every dict in core.DB starts empty on each boot and no entity
is ever seeded, preloaded or hardcoded at startup.
"""
import os

from flask import Flask, g

from core import ApiError, error_response
import routes_catalog
import routes_claims
import routes_logistics
import routes_members
import routes_reservations
import routes_resale
import routes_shipments


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_members.bp)
    app.register_blueprint(routes_reservations.bp)
    app.register_blueprint(routes_shipments.bp)
    app.register_blueprint(routes_logistics.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_resale.bp)

    @app.before_request
    def _reset_touch_set():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "Unknown route"))

    @app.errorhandler(405)
    def _bad_method(_err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INTERNAL", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
