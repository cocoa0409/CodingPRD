"""Application entry point.

Registers the error handlers, mounts the API blueprint and runs the server on
0.0.0.0:$PORT (default 10000) in the foreground.

Storage is in-memory only (see db.py): nothing is persisted and no entity is
seeded, so every fresh `start.sh` invocation boots an empty store.
"""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    """Keep the standard envelope for malformed bodies and unknown routes."""
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", exc.description or "not found", 404)
    return error_response("ERR_INVALID_REQUEST", exc.description or "bad request", exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return error_response("ERR_INVALID_REQUEST", "internal error: %s" % exc, 500)


# The packages are imported after the handlers so their module-level imports
# resolve against the already-initialised application package.
from routing import api  # noqa: E402
import routes  # noqa: E402,F401  (registers every endpoint on the blueprint)

app.register_blueprint(api)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)