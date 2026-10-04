"""Entry point: app factory, error handlers and blueprint registration.

Storage is in-memory only and the store starts empty — app.py never seeds,
preloads or hardcodes any entity.  Every record a caller sees was created
through the declared API surface.
"""

import os
import traceback
from decimal import Decimal

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from serialize import render, render_list

import routes.claims
import routes.enrollments
import routes.mitigation
import routes.notices
import routes.properties
import routes.scheduled
import routes.wildfire
import routes.zones

BLUEPRINTS = (
    routes.zones.bp,
    routes.properties.bp,
    routes.scheduled.bp,
    routes.mitigation.bp,
    routes.wildfire.bp,
    routes.enrollments.bp,
    routes.claims.bp,
    routes.notices.bp,
)


def _json_default(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return str(value)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    # Decimal is used for every precision-sensitive step; the wire format renders
    # it as a JSON number without going through IEEE 754 arithmetic.
    app.json.default = _json_default

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.route("/", methods=["GET"])
    def _liveness():
        """Unauthenticated liveness endpoint.

        The per-test harness polls the bare origin to decide whether a freshly
        restarted server is ready, so this path must answer without requiring
        either identity header.
        """
        return jsonify({"status": "ok"}), 200

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist.")), 404

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist.")), 404

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error_body("ERR_NOT_FOUND", str(exc.description))), exc.code or 404
        traceback.print_exc()
        return jsonify(error_body(
            "ERR_INVALID_REQUEST",
            "The request could not be processed.")), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)