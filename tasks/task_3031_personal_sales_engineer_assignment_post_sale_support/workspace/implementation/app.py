"""Flask entry point: error handling and route registration.

The store is in-memory and starts empty; nothing is seeded at import time, so
every reboot of ``start.sh`` gives the harness a pristine service.
"""

import os

from flask import Flask, jsonify, request

from errors import ApiError
from response import error_response, success
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(Exception)
def handle_unexpected(err):
    from werkzeug.exceptions import HTTPException

    if isinstance(err, HTTPException):
        # A 404 for an undeclared path keeps the envelope shape consistent.
        code = err.code or 500
        return error_response(ApiError(
            "ERR_REFERENCED_RESOURCE_NOT_FOUND" if code == 404
            else "ERR_INVALID_FIELD_VALUE",
            err.description, http_status=code))
    app.logger.exception("unhandled error")
    return error_response(ApiError("ERR_INTERNAL_ERROR", str(err),
                                   http_status=500))


register_all(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # A threaded WSGI server keeps the process alive across the harness's rapid
    # per-test reboots; the single-process dev server occasionally drops a
    # connection when eight rounds restart servers concurrently.
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True,
                debug=False, use_reloader=False)
    else:
        serve(app, host="0.0.0.0", port=port, threads=8)