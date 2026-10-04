"""Entry point: wires the route groups, the envelope error handlers and the
logical clock. The store starts empty on every boot; nothing is seeded."""

import os

from flask import Flask, request

from errors import ApiError
from response import error_envelope
from routes.authorizations import bp as authorizations_bp
from routes.clients import bp as clients_bp
from routes.deliveries import bp as deliveries_bp
from routes.enrollments import bp as enrollments_bp
from routes.finance import bp as finance_bp
from routes.foundation import bp as foundation_bp
from routes.intake import bp as intake_bp
from services import eligibility

app = Flask(__name__)
app.url_map.strict_slashes = False

API_PREFIX = "/api"

for blueprint in (
    foundation_bp,
    clients_bp,
    intake_bp,
    enrollments_bp,
    authorizations_bp,
    deliveries_bp,
    finance_bp,
):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


@app.before_request
def _expire_stale_screens():
    """A system event evaluated on every write: a VERIFIED-but-PENDING screen
    expires once the logical clock is 180 days past screened_at."""
    eligibility.expire_stale_screens()


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_envelope(error), error.http_status


@app.errorhandler(404)
def _handle_not_found(_error):
    return error_envelope(ApiError("ERR_INVALID_STATE", "The requested route does not exist.")), 404


@app.errorhandler(405)
def _handle_method_not_allowed(_error):
    return error_envelope(
        ApiError("ERR_INVALID_STATE", "The method is not allowed for this route.")
    ), 405


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return error_envelope(error), error.http_status
    return error_envelope(
        ApiError("ERR_INVALID_STATE", "Unexpected server error: %s" % error, 500)
    ), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
