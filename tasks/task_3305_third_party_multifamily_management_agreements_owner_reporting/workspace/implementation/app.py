"""Flask entry point for the Multifamily Management Agreements API."""

import os

from flask import Flask

from errors import ApiError, not_found, invalid_request
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_owners
import routes_onboarding
import routes_budgets
import routes_pricing
import routes_staff_ledger
import routes_statements
import routes_reports
import routes_claims
import routes_clock

app.register_blueprint(routes_owners.bp)
app.register_blueprint(routes_onboarding.bp)
app.register_blueprint(routes_budgets.bp)
app.register_blueprint(routes_pricing.bp)
app.register_blueprint(routes_staff_ledger.bp)
app.register_blueprint(routes_statements.bp)
app.register_blueprint(routes_reports.bp)
app.register_blueprint(routes_claims.bp)
app.register_blueprint(routes_clock.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(not_found("Resource does not exist"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(not_found("Method not allowed for this resource"))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(invalid_request(str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
