"""Student Teacher Placement & Clinical Practice API.

In-memory Flask application: no persistence, no seeded data. Every entity is
built by the declared endpoints.
"""

import os
import traceback

from flask import Flask

import envelope
import store
from errors import ApiError
from routes import admin as admin_routes
from routes import agreements as agreement_routes
from routes import assessments as assessment_routes
from routes import bench as bench_routes
from routes import candidates as candidate_routes
from routes import cycles as cycle_routes
from routes import districts as district_routes
from routes import items as item_routes
from routes import placements as placement_routes
from routes import requests as request_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in (district_routes, candidate_routes, item_routes,
                   agreement_routes, bench_routes, request_routes,
                   placement_routes, cycle_routes, assessment_routes,
                   admin_routes):
        app.register_blueprint(module.bp)

    @app.before_request
    def _new_request():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "No such endpoint.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error("ERR_INVALID_REQUEST",
                             "The HTTP method is not allowed here.", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        traceback.print_exc()
        return envelope.error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
