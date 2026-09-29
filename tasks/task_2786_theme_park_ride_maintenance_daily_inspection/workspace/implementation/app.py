"""Theme Park Ride Maintenance & Daily Inspection API.

Flask application factory and wiring. All state lives in process memory
(see store.py); nothing is seeded at start-up and nothing is written to disk,
so every fresh boot begins with an empty park and the logical clock parked at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g, jsonify, request

import derive
from envelope import error_body
from errors import ApiError, ERR_INVALID_REQUEST, STATUS
import routes_attractions
import routes_bulletins
import routes_certifications
import routes_clock
import routes_components
import routes_downtime
import routes_incidents
import routes_inspections
import routes_overhaul
import routes_requisitions
import routes_templates

BLUEPRINTS = (
    routes_attractions.bp,
    routes_components.bp,
    routes_templates.bp,
    routes_inspections.bp,
    routes_bulletins.bp,
    routes_downtime.bp,
    routes_requisitions.bp,
    routes_certifications.bp,
    routes_incidents.bp,
    routes_overhaul.bp,
    routes_clock.bp,
)

CLOCK_PATH = "/_clock/set_current_utc"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def capture_pre_state():
        """Snapshot every row so version bumps can be reconciled once."""
        g.pre_snapshot = None
        if request.method == "GET" or request.path == CLOCK_PATH:
            return None
        g.pre_snapshot = derive.snapshot_all()
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "No such resource.")), 404

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return jsonify(error_body(
            ERR_INVALID_REQUEST,
            "The HTTP method is not allowed on this path.")), \
            STATUS[ERR_INVALID_REQUEST]

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INTERNAL",
                                  "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
