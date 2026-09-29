"""Vascular Access Center / Dialysis Access Maintenance API.

Entry point.  Registers the route blueprints and installs the uniform error
envelope of PRD section 2.3.  All state lives in process memory (core.db) and
is discarded when the process exits: nothing is seeded at startup.
"""
import os
import threading

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, envelope_error
import routes_access
import routes_plan
import routes_procedure
import routes_reference
import routes_referral


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_access.bp)
    app.register_blueprint(routes_referral.bp)
    app.register_blueprint(routes_procedure.bp)
    app.register_blueprint(routes_plan.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(envelope_error(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        # Unrouted paths and unsupported methods still answer in the envelope.
        if exc.code == 404:
            return jsonify(envelope_error("ERR_INVALID_REQUEST", "resource not found")), 404
        if exc.code == 405:
            return jsonify(envelope_error("ERR_INVALID_REQUEST", "method not allowed")), 405
        if exc.code in (400, 415):
            return jsonify(envelope_error("ERR_INVALID_REQUEST",
                                          "request body failed shape validation")), 422
        return jsonify(envelope_error("ERR_INVALID_REQUEST", exc.name)), exc.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(envelope_error("ERR_INVALID_REQUEST", "unexpected server error")), 500

    # One request at a time: every cascade in the PRD must observe a consistent
    # snapshot of the in-memory store.
    lock = threading.Lock()
    inner_wsgi = app.wsgi_app

    def serialized_wsgi(environ, start_response):
        with lock:
            return inner_wsgi(environ, start_response)

    app.wsgi_app = serialized_wsgi
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
