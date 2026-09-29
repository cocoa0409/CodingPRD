"""Security Awareness & Phishing Simulation API -- application entry point.

Every boot starts from a completely empty in-memory store: nothing is seeded,
nothing is persisted, and re-running start.sh wipes every byte of state.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_campaigns
import routes_employees
import routes_reports
import routes_simulations
import routes_training
from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_employees.bp)
    app.register_blueprint(routes_training.bp)
    app.register_blueprint(routes_campaigns.bp)
    app.register_blueprint(routes_simulations.bp)
    app.register_blueprint(routes_reports.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_RESOURCE_NOT_FOUND", "no such route")), 404
        if exc.code == 405:
            return jsonify(
                error_body("ERR_INVALID_REQUEST", "method not allowed on this route")), 405
        if exc.code == 400:
            return jsonify(error_body("ERR_INVALID_REQUEST", "malformed request")), 400
        if exc.code == 415:
            return jsonify(
                error_body("ERR_INVALID_REQUEST", "unsupported media type")), 400
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "request failed")), \
            exc.code or 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return jsonify(error_body("ERR_INTERNAL", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
