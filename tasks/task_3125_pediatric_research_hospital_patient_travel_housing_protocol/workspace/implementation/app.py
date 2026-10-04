"""Pediatric Research Hospital API — Flask entry point.

Storage is in-memory only: every map in db.DB starts empty on each process boot.
Nothing is seeded, preloaded or dumped to disk, so re-running start.sh always
produces a pristine server.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["PROPAGATE_EXCEPTIONS"] = False

for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    if error.code == 404:
        return error_response(
            "ERR_NOT_FOUND", "A resource id in the path or body does not exist.", 404)
    if error.code == 405:
        return error_response(
            "ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)
    return error_response("ERR_INVALID_REQUEST", error.description, error.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(error):
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", str(error), 400)


@app.errorhandler(500)
def handle_500(error):
    return error_response("ERR_INVALID_REQUEST", "Internal error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, use_reloader=False, threaded=True)