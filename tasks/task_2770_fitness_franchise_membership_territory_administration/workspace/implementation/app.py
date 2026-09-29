"""Fitness Franchise Membership & Territory Administration API.

In-memory only: every entity lives in a process-local dict and nothing is ever
seeded, so a fresh process starts with an empty world and a logical clock
reading 2026-08-01T00:00:00Z.
"""
import os
import traceback

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError
from routes.compliance import bp as compliance_bp
from routes.memberships import bp as memberships_bp
from routes.plans import bp as plans_bp
from routes.spine import bp as spine_bp
from routes.usage import bp as usage_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(spine_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(usage_bp)
    app.register_blueprint(compliance_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_NOT_FOUND", "The requested route does not exist.")), 404

    @app.errorhandler(405)
    def _bad_method(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "That HTTP method is not allowed on this route.")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        code = getattr(exc, "code", None)
        if code == 404:
            return _not_found(exc)
        if code == 405:
            return _bad_method(exc)
        if isinstance(code, int) and 400 <= code < 500:
            return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), code
        traceback.print_exc()
        return jsonify(error_body("ERR_INTERNAL", "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
