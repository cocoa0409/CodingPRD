"""Commercial Kitchen Food Waste Tracking & Diversion API.

All state lives in process memory and starts empty on every boot: nothing is
seeded, preloaded or hardcoded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import baseline, catalog, diversion, entries, ops, quality

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (catalog, ops, entries, baseline, diversion, quality):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return error_response("ERR_INVALID_REQUEST",
                              "The requested resource does not exist.", 404)
    if exc.code == 405:
        return error_response("ERR_INVALID_REQUEST",
                              "That method is not allowed on this resource.", 405)
    if exc.code == 400:
        return error_response("ERR_INVALID_REQUEST",
                              "The request body could not be parsed as JSON.", 400)
    return error_response("ERR_INVALID_REQUEST",
                          exc.description or "Request could not be processed.",
                          exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False)
