"""Sidewalk delivery robot operations API - entry point.

The in-memory store starts completely empty on every boot; nothing is seeded.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.bays import bp as bays_bp
from routes.clock import bp as clock_bp
from routes.closures import bp as closures_bp
from routes.incidents import bp as incidents_bp
from routes.interventions import bp as interventions_bp
from routes.merchants import bp as merchants_bp
from routes.missions import bp as missions_bp
from routes.orders import bp as orders_bp
from routes.plans import bp as plans_bp
from routes.robots import bp as robots_bp
from routes.segments import bp as segments_bp
from routes.zones import bp as zones_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        clock_bp,
        zones_bp,
        segments_bp,
        closures_bp,
        merchants_bp,
        robots_bp,
        bays_bp,
        orders_bp,
        missions_bp,
        plans_bp,
        interventions_bp,
        incidents_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        use_reloader=False,
    )
