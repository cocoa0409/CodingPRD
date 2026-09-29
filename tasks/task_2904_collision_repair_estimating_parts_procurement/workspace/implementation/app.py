"""Collision Repair Estimating and Parts Procurement API.

In-memory only: every process starts with an empty store and no seeded rows.
"""
import os

from flask import Flask, jsonify

import response
from errors import ApiError, CATALOG
from routes import assignments, estimate_lines, orders, parts, procedures, registry, supplements


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(registry.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(estimate_lines.bp)
    app.register_blueprint(supplements.bp)
    app.register_blueprint(parts.bp)
    app.register_blueprint(procedures.bp)
    app.register_blueprint(assignments.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        body = response.error_body("ERR_NOT_FOUND", "No such route.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        body = response.error_body("ERR_METHOD_NOT_ALLOWED",
                                   "That method is not allowed on this route.")
        return jsonify(body), 405

    @app.errorhandler(415)
    def handle_unsupported_media(exc):
        body = response.error_body("ERR_INVALID_REQUEST",
                                   "Request body must be JSON.")
        return jsonify(body), 400

    @app.errorhandler(400)
    def handle_bad_request(exc):
        body = response.error_body("ERR_INVALID_REQUEST", "The request is invalid.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = response.error_body("ERR_INTERNAL", str(exc))
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    assert CATALOG
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
