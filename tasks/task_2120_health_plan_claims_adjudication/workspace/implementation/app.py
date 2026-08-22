"""Health Plan Claims Adjudication API.

Storage is in-memory only and starts empty on every boot: no entity is seeded,
preloaded or hardcoded. Every row is created through the declared API surface.
"""

import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError
from routes.authorizations import bp as authorizations_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.config import bp as config_bp
from routes.members import bp as members_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return jsonify(error_body("ERR_CLAIM_NOT_FOUND", "No such resource.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return jsonify(error_body("ERR_FORBIDDEN_ROLE", "Method not allowed.")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error", exc_info=exc)
        return jsonify(error_body("ERR_INVALID_FIELD_VALUE", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
