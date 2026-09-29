"""Affiliate Marketing Program Management API.

Flask application factory and entry point.  All state lives in memory and is
lost on every process exit -- the test harness relaunches the server before
every test, so the store must start completely empty each time.
"""

import os

from flask import Flask, jsonify

import routes_a
import routes_b
import routes_c
import routes_d
import routes_e
import routes_f
from common import ApiError, error_response

MODULES = (routes_a, routes_b, routes_c, routes_d, routes_e, routes_f)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for module in MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return _envelope("ERR_INVALID_REQUEST", "no such route", 404)

    @app.errorhandler(405)
    def _not_allowed(err):
        return _envelope("ERR_INVALID_REQUEST",
                         "method not allowed on this route", 405)

    @app.errorhandler(400)
    def _bad_request(err):
        return _envelope("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return _envelope("ERR_INVALID_REQUEST", "unhandled server error", 500)

    return app


def _envelope(error_id, message, status):
    from common import _meta
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
