"""Pressure Vessel Fabrication API — application entry point.

The store is empty at boot: no entity is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask

import response
from errors import ApiError

from routes import certificates as certificates_routes
from routes import calculations as calculations_routes
from routes import exams as exams_routes
from routes import jobs as jobs_routes
from routes import materials as materials_routes
from routes import personnel as personnel_routes
from routes import pwht as pwht_routes
from routes import reports as reports_routes
from routes import tests as tests_routes
from routes import welding as welding_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (personnel_routes, certificates_routes, jobs_routes,
                   calculations_routes, materials_routes, welding_routes,
                   exams_routes, pwht_routes, tests_routes, reports_routes):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "Method not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
