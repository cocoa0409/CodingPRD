"""Application entry point.

Registers every route blueprint and installs the error envelope handlers.
The process holds all state in memory (`db.store`) and starts with every
collection empty: no entity is seeded, preloaded or hardcoded at boot.
"""

import os
import sys

from flask import Flask, jsonify, request

# Ensure sibling modules resolve when the launcher invokes `python3 app.py`
# from the implementation directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error_body, success_object  # noqa: E402

from routes import (  # noqa: E402
    area,
    assistance,
    base,
    depots,
    rides,
    roadside,
    territories,
    vehicles,
    waves,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        base.bp,
        territories.bp,
        depots.bp,
        vehicles.bp,
        waves.bp,
        area.bp,
        rides.bp,
        assistance.bp,
        roadside.bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return jsonify(error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(404)
    def _handle_not_found(_error):
        return jsonify(error_body("ERR_NOT_FOUND", "Path resource does not exist.")), 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(_error):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed for this path.")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        if isinstance(error, ApiError):
            return jsonify(error_body(error.error_id, error.message)), error.http_status
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request: %s" % error)),
            400,
        )

    @app.route("/")
    def _root():
        return success_object({"service": "autonomous-ride-hailing-depot-ops", "status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)