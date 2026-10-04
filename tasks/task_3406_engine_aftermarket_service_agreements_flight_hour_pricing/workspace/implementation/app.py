"""Application entry point: Flask app, error handlers, route registration.

Boots cleanly from a fresh process on every invocation; the store starts empty
and the logical clock reads 2026-09-01T00:00:00Z until advanced.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_admin
import routes_agreements
import routes_billing
import routes_directives
import routes_leasing
import routes_parts
import routes_reports
import routes_visits
import routes_workscopes

for module in (
    routes_admin,
    routes_agreements,
    routes_billing,
    routes_directives,
    routes_leasing,
    routes_parts,
    routes_reports,
    routes_visits,
    routes_workscopes,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(Exception)
def handle_unexpected(err):
    """Last-resort JSON envelope for anything uncaught (keeps failures
    structured). Flask HTTPExceptions (unmatched routes etc.) keep their own
    status code; anything else is a 500."""
    from flask import jsonify
    from werkzeug.exceptions import HTTPException

    from envelope import _meta

    if isinstance(err, HTTPException):
        status = err.code
        error_id = "ERR_NOT_FOUND" if status == 404 else "ERR_HTTP_{}".format(status)
        message = err.description
    else:
        status = 500
        error_id = "ERR_INTERNAL"
        message = "internal error: {}".format(err)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": str(message)},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
