"""App entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)

from routes.programs import bp as programs_bp
from routes.assets import bp as assets_bp
from routes.scope_versions import bp as scope_versions_bp
from routes.researchers import bp as researchers_bp
from routes.invitations import bp as invitations_bp
from routes.reports import bp as reports_bp
from routes.awards import bp as awards_bp
from routes.disclosure_requests import bp as disclosure_bp
from routes.remediation_tickets import bp as tickets_bp
from routes.clock_routes import bp as clock_bp

for bp in (
    programs_bp, assets_bp, scope_versions_bp, researchers_bp, invitations_bp,
    reports_bp, awards_bp, disclosure_bp, tickets_bp, clock_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
