"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.service_providers import bp as sp_bp
from routes.members import bp as members_bp
from routes.payees import bp as payees_bp
from routes.works import bp as works_bp
from routes.rate_schedules import bp as schedules_bp
from routes.usage import bp as usage_bp
from routes.match_runs import bp as match_runs_bp
from routes.accruals import bp as accruals_bp
from routes.claims import bp as claims_bp
from routes.disputes import bp as disputes_bp
from routes.statements import bp as statements_bp
from routes.audits import bp as audits_bp
from routes.cycle_runs import bp as cycles_bp
from routes.clock import bp as clock_bp

for bp in (sp_bp, members_bp, payees_bp, works_bp, schedules_bp, usage_bp,
           match_runs_bp, accruals_bp, claims_bp, disputes_bp, statements_bp,
           audits_bp, cycles_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Not found", 404))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 500))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
