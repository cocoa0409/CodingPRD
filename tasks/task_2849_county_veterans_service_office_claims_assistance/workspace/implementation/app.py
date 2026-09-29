"""County Veterans Service Office claims-assistance API (Flask entry point).

All state lives in process memory only (see store.py); a fresh process starts
with every collection empty and nothing pre-registered.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_claims
import routes_exams
import routes_intake
import routes_registry
import routes_state


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_intake.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_exams.bp)
    app.register_blueprint(routes_state.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 422:
            return error_response("ERR_VALIDATION", "request is not valid", 422)
        if exc.code in (400, 415):
            return error_response("ERR_VALIDATION",
                                  "request body is not valid JSON", 422)
        return error_response("ERR_NOT_FOUND",
                              "no such endpoint", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION",
                              "request could not be processed: %s" % (exc,),
                              422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
