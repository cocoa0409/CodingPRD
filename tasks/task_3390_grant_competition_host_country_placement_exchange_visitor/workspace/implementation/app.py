"""Flask entry point: registers all route blueprints and the error handlers
that render every failure in the PRD 2.2 error envelope."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes_clock import bp as clock_bp
from routes_cycles import bp as cycles_bp
from routes_applicants import bp as applicants_bp
from routes_applications import bp as applications_bp
from routes_rounds import bp as rounds_bp
from routes_grants import bp as grants_bp
from routes_visa import bp as visa_bp
from routes_reports import bp as reports_bp
from routes_incidents import bp as incidents_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(clock_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(rounds_bp)
    app.register_blueprint(grants_bp)
    app.register_blueprint(visa_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(incidents_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return envelope.error(err.error_id, err.http_status, err.message)

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        # Unmatched routes / methods still return the error envelope.
        code = err.code or 500
        error_id = "ERR_VALIDATION" if code == 400 else "ERR_NOT_FOUND" if code in (404, 405) else "ERR_INTERNAL"
        return envelope.error(error_id, code, err.description or "HTTP error")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return envelope.error("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
