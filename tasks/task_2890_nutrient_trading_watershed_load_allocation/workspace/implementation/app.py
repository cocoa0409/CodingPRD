"""Nutrient Trading & Watershed Load Allocation API.

A single-process Flask service holding all state in memory.  Nothing is
persisted and nothing is seeded: every row is created through the API.
"""
import logging
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
import routes_market
import routes_permits
import routes_program
import routes_tmdl

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_program.bp)
app.register_blueprint(routes_tmdl.bp)
app.register_blueprint(routes_permits.bp)
app.register_blueprint(routes_market.bp)

_request_lock = threading.Lock()


@app.before_request
def _begin_request():
    _request_lock.acquire()
    g._holds_lock = True
    g.touched = set()


@app.teardown_request
def _end_request(exception=None):
    if g.pop("_holds_lock", False):
        try:
            _request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(error):
    status = error.code or 500
    if status == 404:
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
    if status == 405:
        return error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this resource.", 405
        )
    if status == 415 or status == 400:
        return error_response("ERR_INVALID_REQUEST", "The request could not be understood.", 422)
    return error_response("ERR_INTERNAL", error.description or "Request failed.", status)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    app.logger.exception("unhandled error")
    return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
