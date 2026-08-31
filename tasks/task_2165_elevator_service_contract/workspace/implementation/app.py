"""Elevator Service Contract Management API — entry point.

Storage is entirely in-memory and starts empty on every boot: no seeding,
no preloading, no persistence of any kind.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response, base_meta
from routes.contracts import bp as contracts_bp
from routes.cars import bp as cars_bp
from routes.visits import bp as visits_bp
from routes.callbacks import bp as callbacks_bp
from routes.inspections import bp as inspections_bp
from routes.projects import bp as projects_bp
from routes.windows import bp as windows_bp
from routes.parts import bp as parts_bp
from routes.part_orders import bp as part_orders_bp
from routes.penalties import bp as penalties_bp
from routes.renegotiations import bp as renegotiations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (contracts_bp, cars_bp, visits_bp, callbacks_bp,
                      inspections_bp, projects_bp, windows_bp, parts_bp,
                      part_orders_bp, penalties_bp, renegotiations_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        payload, status = error_response(exc.error_id, exc.message)
        return jsonify(payload), status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            payload, status = error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
            return jsonify(payload), status
        if exc.code == 405:
            payload, status = error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.")
            return jsonify(payload), 404
        if exc.code == 400:
            payload, status = error_response("ERR_VALIDATION", "Malformed request.")
            return jsonify(payload), status
        body = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": exc.description or "Error."},
        }
        return jsonify(body), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        body = {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(exc)},
        }
        return jsonify(body), 500

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
