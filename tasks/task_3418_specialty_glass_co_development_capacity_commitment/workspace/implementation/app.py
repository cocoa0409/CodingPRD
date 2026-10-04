"""Entry point: Flask app factory, error handlers, blueprint registration."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_payload

import routes_allocations
import routes_campaigns
import routes_commitments
import routes_compositions
import routes_device_makers
import routes_licenses
import routes_programs
import routes_qual_cycles
import routes_system
import routes_tanks
import routes_usage_reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_payload(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_not_found(_err):
        return jsonify(error_payload(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return jsonify(error_payload(ERR_INVALID_REQUEST, "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        return jsonify(error_payload("ERR_INTERNAL", str(err))), 500

    for module in (
        routes_device_makers,
        routes_programs,
        routes_compositions,
        routes_qual_cycles,
        routes_tanks,
        routes_campaigns,
        routes_commitments,
        routes_allocations,
        routes_licenses,
        routes_usage_reports,
        routes_system,
    ):
        app.register_blueprint(module.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        use_reloader=False,
    )
