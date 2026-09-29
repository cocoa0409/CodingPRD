"""Fish Hatchery Stocking API - Flask application factory and entry point.

State lives in process memory only (see store.py): every launch of start.sh
boots a completely empty world, and nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_brood
import routes_event
import routes_hatchery
import routes_health
import routes_lot
import routes_plan
import routes_request
import routes_transport
import routes_water
from envelope import _meta, error_response
from errors import ApiError

BLUEPRINTS = (
    routes_hatchery.bp,
    routes_water.bp,
    routes_brood.bp,
    routes_lot.bp,
    routes_health.bp,
    routes_request.bp,
    routes_plan.bp,
    routes_transport.bp,
    routes_event.bp,
)


def _plain_error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return error_response(error)

    @app.errorhandler(HTTPException)
    def _handle_http_error(error):
        if error.code == 404:
            return _plain_error("ERR_NOT_FOUND", "No such route.", 404)
        if error.code == 405:
            return _plain_error("ERR_METHOD_NOT_ALLOWED",
                                "That method is not allowed on this route.", 405)
        if error.code == 400:
            return _plain_error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return _plain_error("ERR_INVALID_REQUEST", error.description or "Request failed.",
                            error.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        return _plain_error("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
