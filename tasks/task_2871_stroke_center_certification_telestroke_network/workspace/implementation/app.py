"""Stroke Center Certification and Telestroke Network API.

Entry point: blueprint registration, the logical-clock control endpoint and
the error envelope.  Storage is in-memory and starts completely empty on
every boot: no entity is ever seeded here.
"""
import os

from flask import Flask, g

import db
import response as resp
from errors import ApiError, HTTP_STATUS
from middleware import Field, authenticate, read_body
from routes.abstractions import bp as abstractions_bp
from routes.agreements import bp as agreements_bp
from routes.cases import bp as cases_bp
from routes.centers import bp as centers_bp
from routes.checklists import bp as checklists_bp
from routes.consults import bp as consults_bp
from routes.deviations import bp as deviations_bp
from routes.neurologists import bp as neurologists_bp
from routes.reports import bp as reports_bp
from routes.transfers import bp as transfers_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

MOUNT = "/stroke-network"

for blueprint in (centers_bp, agreements_bp, neurologists_bp, cases_bp,
                  consults_bp, checklists_bp, transfers_bp, deviations_bp,
                  abstractions_bp, reports_bp):
    app.register_blueprint(blueprint, url_prefix=MOUNT)

CLOCK_SPEC = [Field("current_utc", "dt")]


@app.before_request
def _reset_touch_tracking():
    g.touched_ids = set()


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    """The one endpoint outside the /stroke-network mount; it mutates no entity."""
    authenticate("any")
    body = read_body(CLOCK_SPEC)
    db.CLOCK.set(body["current_utc"])
    return resp.empty_response()


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return resp.error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def _handle_not_found(_error):
    return resp.error_response(
        "ERR_NOT_FOUND", "No route matches the requested path.", 404)


@app.errorhandler(405)
def _handle_method_not_allowed(_error):
    return resp.error_response(
        "ERR_NOT_FOUND", "The method is not allowed for the requested path.", 405)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return _handle_api_error(error)
    app.logger.exception("unhandled error")
    return resp.error_response(
        "ERR_INVALID_REQUEST", "The request could not be processed: %s" % error,
        HTTP_STATUS.get("ERR_INVALID_REQUEST", 422))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
