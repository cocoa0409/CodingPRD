"""DispatchHealth API server entry point."""
import os

from flask import Flask

import db
import helpers as H
from errors import ApiError, raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_AUTH_HEADER
from middleware import require_roles
from response import error_response, success_object

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND[0], "resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND[0], "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    app.logger.exception("unexpected error")
    return error_response(ERR_INVALID_REQUEST[0], "invalid request", 400)


@app.post("/dh/_clock/set_current_utc")
def set_clock():
    require_roles({"PlatformAdmin"})
    body = H.get_json_body()
    current_utc = H.require(body, "current_utc", "datetime")
    # Normalize to canonical Z form
    canonical = H.fmt_dt(H.parse_dt(current_utc))
    with db.lock():
        db.set_clock(canonical)
    return success_object({"current_utc": canonical})


# Register route modules
from routes import admin, capacity, visits, dispatch, encounters, clinical  # noqa: E402

admin.register(app)
capacity.register(app)
visits.register(app)
dispatch.register(app)
encounters.register(app)
clinical.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
