"""Termite Bond & Wood-Destroying-Organism Inspection API.

Flask application factory and error plumbing.  Every route lives in a
blueprint under routes_*.py; all state lives in the in-memory store of
store.py, so a fresh process starts with an empty database and the logical
clock parked at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_bond
import routes_claim
import routes_core
import routes_inspection
import routes_plan
import routes_renewal
import routes_station
import routes_wdo
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_inspection.bp)
    app.register_blueprint(routes_plan.bp)
    app.register_blueprint(routes_station.bp)
    app.register_blueprint(routes_bond.bp)
    app.register_blueprint(routes_renewal.bp)
    app.register_blueprint(routes_wdo.bp)
    app.register_blueprint(routes_claim.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_INVALID_REQUEST",
                                  "no route matches this path", 404)
        if status == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "this method is not allowed on this path", 405)
        if status == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "the request could not be parsed", 400)
        return error_response("ERR_INVALID_REQUEST", exc.name, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc,
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
