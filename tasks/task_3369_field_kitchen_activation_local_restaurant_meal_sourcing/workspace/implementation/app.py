"""Flask entry point for the field-kitchen-activation API.

The store is in-memory and starts empty on every boot: nothing is seeded,
preloaded or written to disk, so a fresh `bash start.sh` always yields a clean
process with no carry-over state from the previous run.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import error_envelope
from errors import ApiError
from routes import bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["PROPAGATE_EXCEPTIONS"] = False
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def _api_error(error):
    return error_envelope(error.error_id, error.message), error.http_status


@app.errorhandler(HTTPException)
def _http_error(error):
    error_id = "ERR_RESOURCE_NOT_FOUND" if error.code == 404 else "ERR_INVALID_REQUEST"
    return error_envelope(error_id, error.description or "Request rejected."), error.code


@app.errorhandler(Exception)
def _unexpected(error):
    return error_envelope("ERR_INVALID_REQUEST", "The request could not be processed."), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        use_reloader=False,
        threaded=True,
    )
