"""Entry point: Flask app, error handlers, logical-clock endpoint, route
registration. All state is in-memory and starts empty on every boot."""

import os

from flask import Flask

from auth import require_roles
from errors import ApiError
from response import err_response, ok_empty
from store import CLOCK
from validate import get_body, req_timestamp

app = Flask(__name__)

import routes_advising
import routes_aid
import routes_enroll
import routes_funnel
import routes_terms

app.register_blueprint(routes_terms.bp)
app.register_blueprint(routes_funnel.bp)
app.register_blueprint(routes_enroll.bp)
app.register_blueprint(routes_aid.bp)
app.register_blueprint(routes_advising.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return err_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return err_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return err_response("ERR_INVALID_REQUEST", 400, "unhandled error: %s" % err)


@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("SystemAdmin")
    body = get_body()
    _raw, dt = req_timestamp(body, "to_iso8601")
    CLOCK.set(dt)
    return ok_empty(200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
