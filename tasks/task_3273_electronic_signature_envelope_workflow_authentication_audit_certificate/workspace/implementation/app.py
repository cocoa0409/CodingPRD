"""Esign Envelope Workflow API — entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. Storage is in-memory
only; the store starts empty on every boot and no entity data is seeded.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    return error_body(
        "ERR_INVALID_REQUEST",
        exc.description or "the request could not be handled",
        exc.code or 400,
    )


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return error_body("ERR_INVALID_REQUEST", str(exc), 400)


@app.errorhandler(404)
def _handle_404(exc):
    return error_body("ERR_INVALID_REQUEST", "no such route", 400)


@app.errorhandler(405)
def _handle_405(exc):
    return error_body("ERR_INVALID_REQUEST", "method not allowed", 400)


import routes  # noqa: E402

routes.register(app)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)