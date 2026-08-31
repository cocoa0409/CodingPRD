"""Deposit Account Fraud & Kiting Detection API — Flask entry point.

In-memory storage only. The store starts empty on every boot; every entity is
created by callers through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_a
import routes_b
import routes_c

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    if err.code == 404:
        return error_response(ApiError("ERR_ACCOUNT_NOT_FOUND", "Unknown route."))
    if err.code in (400, 415):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request."))
    # Anything else (405, 413, ...) keeps its own HTTP status in the envelope.
    body = ApiError("ERR_INVALID_REQUEST", err.description or str(err))
    body.http_status = err.code or 500
    return error_response(body)


@app.errorhandler(Exception)
def handle_unexpected(err):  # pragma: no cover - defensive
    app.logger.exception("Unhandled error: %s", err)
    return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected server error."))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
