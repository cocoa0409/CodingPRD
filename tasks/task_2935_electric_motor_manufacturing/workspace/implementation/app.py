"""Electric Motor Manufacturing API.

Storage is process-local and in-memory only: every invocation of start.sh boots
a completely empty plant with the logical clock at its 2026-08-01T00:00:00Z
default.  Nothing is seeded, preloaded or persisted anywhere.
"""

import json
import os

from flask import Flask, Response
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from store import wall_iso3

import routes_builds
import routes_design
import routes_orders
import routes_reference
import routes_tests
import routes_warranty


def envelope_error(error_id, message, status):
    from envelope import request_id
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": wall_iso3(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(json.dumps(body), status=status, mimetype="application/json")


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_design.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_builds.bp)
    app.register_blueprint(routes_tests.bp)
    app.register_blueprint(routes_warranty.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return envelope_error("ERR_INVALID_REQUEST", err.description or err.name,
                              err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return envelope_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err,
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
