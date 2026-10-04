"""Teacher Portfolio Certification API — Flask entry point.

Reads PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes_clock import bp as clock_bp
from routes_cycles import bp as cycles_bp
from routes_candidates import bp as candidates_bp
from routes_submissions import bp as submissions_bp
from routes_artifacts import bp as artifacts_bp
from routes_centers import bp as centers_bp
from routes_bookings import bp as bookings_bp
from routes_assessors import bp as assessors_bp
from routes_scoring import bp as scoring_bp
from routes_certifications import bp as certifications_bp
from routes_incentives import bp as incentives_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in (clock_bp, cycles_bp, candidates_bp, submissions_bp,
                      artifacts_bp, centers_bp, bookings_bp, assessors_bp,
                      scoring_bp, certifications_bp, incentives_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return response.error_response(
            ApiError("ERR_NOT_FOUND", 404, "Route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return response.error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return response.error_response(
            ApiError("ERR_INTERNAL", 500, "Internal error: %s" % err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
