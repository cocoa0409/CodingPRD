"""Baggage Handling Operations API — Flask entry point.

State lives only in process memory (see db.py); a fresh `start.sh` boot starts
from an empty store and nothing is ever seeded.
"""

import functools
import os
import sys
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body, success

import routes_reference
import routes_bags
import routes_screening
import routes_transfer
import routes_reports
import routes_ops

app = Flask(__name__)

for blueprint in (
    routes_reference.bp,
    routes_bags.bp,
    routes_screening.bp,
    routes_transfer.bp,
    routes_reports.bp,
    routes_ops.bp,
):
    app.register_blueprint(blueprint)


def _enveloped(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        result = view(*args, **kwargs)
        status = 200
        pagination = None
        if isinstance(result, tuple):
            data = result[0]
            for extra in result[1:]:
                if isinstance(extra, dict):
                    pagination = extra
                elif isinstance(extra, int):
                    status = extra
        else:
            data = result
        response_type = "array" if isinstance(data, list) else "object"
        body, code = success(data, response_type, pagination)
        return body, status if status != 200 else code

    return wrapper


for endpoint, view in list(app.view_functions.items()):
    app.view_functions[endpoint] = _enveloped(view)


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(Exception)
def _unexpected(exc):
    if isinstance(exc, HTTPException):
        if exc.code == 405:
            return error_body("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
        return error_body("ERR_INVALID_REQUEST",
                          "No route matches the request." if exc.code == 404
                          else "The request could not be processed.",
                          exc.code or 400)
    traceback.print_exc(file=sys.stderr)
    return error_body("ERR_INVALID_REQUEST", "The request could not be processed.", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)