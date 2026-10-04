"""Veteran Program Outcomes API — Flask entry point.

Boots from a fresh process with a completely empty in-memory store and the
logical clock at exactly 2026-09-01T00:00:00Z (PRD section 2.5).
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes_core import bp as core_bp
from routes_enrollments import bp as enrollments_bp
from routes_claims import bp as claims_bp
from routes_referrals import bp as referrals_bp
from routes_placements import bp as placements_bp
from routes_events import bp as events_bp
from routes_surveys import bp as surveys_bp

app = Flask(__name__)
app.json.sort_keys = False

app.register_blueprint(core_bp)
app.register_blueprint(enrollments_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(referrals_bp)
app.register_blueprint(placements_bp)
app.register_blueprint(events_bp)
app.register_blueprint(surveys_bp)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return response.error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def _handle_not_found(err):
    return response.error("ERR_NOT_FOUND", "the requested path does not exist", 404)


@app.errorhandler(405)
def _handle_method_not_allowed(err):
    return response.error("ERR_METHOD_NOT_ALLOWED", "method not allowed on this path", 405)


@app.errorhandler(Exception)
def _handle_exception(err):
    return response.error("ERR_INTERNAL", "internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
