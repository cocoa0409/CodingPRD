"""Athletics Academic Eligibility service — Flask entry point.

State lives in plain in-memory dicts and starts completely empty on every boot;
nothing is seeded, preloaded or persisted anywhere.
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_catalog
import routes_cert
import routes_compliance
import routes_students
import routes_support
import routes_travel
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_students.bp)
app.register_blueprint(routes_cert.bp)
app.register_blueprint(routes_support.bp)
app.register_blueprint(routes_travel.bp)
app.register_blueprint(routes_compliance.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return envelope.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    status = exc.code or 400
    if status == 404:
        message = "The requested resource path does not exist."
    elif status == 405:
        message = "The HTTP method is not allowed for this resource path."
    else:
        message = exc.description or "The request could not be processed."
    return envelope.error_response("ERR_INVALID_REQUEST", message, status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc(file=sys.stderr)
    return envelope.error_response(
        "ERR_INVALID_REQUEST", "The request could not be processed.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
