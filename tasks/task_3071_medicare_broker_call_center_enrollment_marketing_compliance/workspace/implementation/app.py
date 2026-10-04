"""Medicare Broker Compliance API — entry point.

In-memory storage only: the store starts empty on every boot and no entity is
seeded, preloaded or hardcoded. Every entity is constructed through the
declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import ApiError

app = Flask(__name__)
app.json.sort_keys = False
app.url_map.strict_slashes = False
routes.register_all(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    error_id = "ERR_NOT_FOUND" if exc.code == 404 else "ERR_INVALID_REQUEST"
    return response.error(error_id, exc.description or "Request failed.", exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return response.error("ERR_INVALID_REQUEST", str(exc), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)