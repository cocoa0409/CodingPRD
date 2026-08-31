"""Screenplay Coverage & Development Slate API — entry point.

The store is in-memory and starts completely empty on every boot; no entity is
seeded, preloaded or hardcoded here. Tests build all state through the API.
"""

import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, db, error_response
import routes_coverage
import routes_greenlight
import routes_option
import routes_project
import routes_property
import routes_submission
import routes_writer


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_property.bp)
    app.register_blueprint(routes_submission.bp)
    app.register_blueprint(routes_coverage.bp)
    app.register_blueprint(routes_option.bp)
    app.register_blueprint(routes_project.bp)
    app.register_blueprint(routes_writer.bp)
    app.register_blueprint(routes_greenlight.bp)

    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Unknown route."))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed."))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request."))
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))

    @app.errorhandler(Exception)
    def _unexpected(err):
        body = {
            "meta": {"api_request_id": "req_INTERNAL", "api_request_timestamp": ""},
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
        }
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
