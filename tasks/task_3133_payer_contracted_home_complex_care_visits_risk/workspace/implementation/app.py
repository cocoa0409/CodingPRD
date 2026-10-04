"""Flask app entry point. Registers all blueprints and error handlers.

Storage is in-memory only (see db.py); nothing is seeded at startup — the
store starts completely empty on every boot.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)

from routes.programs import bp as programs_bp
from routes.contracts import bp as contracts_bp
from routes.pcp_providers import bp as pcp_bp
from routes.clinicians import bp as clinicians_bp
from routes.members import bp as members_bp
from routes.enrollments import bp as enrollments_bp
from routes.care_teams import bp as care_teams_bp
from routes.visits import bp as visits_bp
from routes.episodes import bp as episodes_bp
from routes.measurements import bp as ops_bp

for bp in (programs_bp, contracts_bp, pcp_bp, clinicians_bp, members_bp,
           enrollments_bp, care_teams_bp, visits_bp, episodes_bp, ops_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(
        ApiError(ERR_INVALID_REQUEST, 400, "Invalid request: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
