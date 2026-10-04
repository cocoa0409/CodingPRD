"""Entry point: app factory, envelope-wrapped error handlers, route wiring."""
import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError
from routes_app_actions import bp as app_actions_bp
from routes_applications import bp as applications_bp
from routes_awards import bp as awards_bp
from routes_certifications import bp as certifications_bp
from routes_clock import bp as clock_bp
from routes_companies import bp as companies_bp
from routes_cycles import bp as cycles_bp
from routes_inspections import bp as inspections_bp
from routes_notices import bp as notices_bp
from routes_reference import bp as reference_bp
from routes_studies import bp as studies_bp
from routes_supplements import bp as supplements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in (
        clock_bp,
        companies_bp,
        reference_bp,
        applications_bp,
        app_actions_bp,
        studies_bp,
        certifications_bp,
        notices_bp,
        cycles_bp,
        inspections_bp,
        supplements_bp,
        awards_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "Route not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "Internal server error")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True)
