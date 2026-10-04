"""Club Chartering, Educational Path Progression & Officer Elections API.

Entry point: registers every router, installs the error envelope handlers and
runs the Flask development server on 0.0.0.0:$PORT (default 10000) in the
foreground.  The in-memory store starts empty on every boot; nothing is seeded.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

import routes_clubs
import routes_contests
import routes_education
import routes_meetings
import routes_members
import routes_officers
import routes_visits

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    routes_clubs,
    routes_members,
    routes_education,
    routes_meetings,
    routes_officers,
    routes_contests,
    routes_visits,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    code = exc.code or 500
    if code == 404:
        error_id = "ERR_NOT_FOUND"
    elif code in (400, 415, 422):
        error_id = "ERR_INVALID_REQUEST"
    elif code == 405:
        error_id = "ERR_NOT_FOUND"
    else:
        error_id = "ERR_INVALID_REQUEST"
    return error_response(error_id, exc.description or error_id, code)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 400)


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
