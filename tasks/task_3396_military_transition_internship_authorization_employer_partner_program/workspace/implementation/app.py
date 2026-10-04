import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (
    clock,
    installations,
    members,
    applications,
    employers,
    openings,
    matches,
    records,
    audits,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

PREFIX = "/skillbridge"
for module in (
    clock,
    installations,
    members,
    applications,
    employers,
    openings,
    matches,
    records,
    audits,
):
    app.register_blueprint(module.bp, url_prefix=PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
