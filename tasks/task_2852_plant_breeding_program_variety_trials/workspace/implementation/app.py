"""Plant Breeding Program Variety Trials API -- Flask application entry point.

State lives entirely in module-level dicts inside store.py, so every fresh
process starts with an empty world (no seeding, no disk persistence).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
import mut
from envelope import respond_error
from errors import ApiError
from routes_gates import bp as gates_bp
from routes_germplasm import bp as germplasm_bp
from routes_program import bp as program_bp
from routes_trials import bp as trials_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    app.register_blueprint(program_bp)
    app.register_blueprint(germplasm_bp)
    app.register_blueprint(trials_bp)
    app.register_blueprint(gates_bp)

    @app.before_request
    def _before():
        mut.reset()
        auth.authenticate()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        code = exc.code or 500
        if code == 404:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The requested resource path does not exist.", 404)
        if code == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The HTTP method is not allowed for this path.", 405)
        if code == 415:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request body must be JSON.", 400)
        if code < 500:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request is malformed or violates a field constraint.", 400)
        return respond_error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error: %s", exc)
        return respond_error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
