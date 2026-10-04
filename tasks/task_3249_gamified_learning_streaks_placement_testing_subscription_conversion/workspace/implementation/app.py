"""Entry point: error handlers, route registration, health check, foreground run.

The store starts empty on every boot — no seeding, no preloading, no hardcoded
entities. Every entity is constructed through a declared endpoint.
"""

import os

from flask import Flask, jsonify

import core
import routes
from core import ApiError

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(core.error_envelope(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return (
        jsonify(core.error_envelope(core.ERR_INVALID_REQUEST, "The requested path does not exist.")),
        404,
    )


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return (
        jsonify(core.error_envelope(core.ERR_INVALID_REQUEST, "The method is not allowed for this path.")),
        405,
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        if exc.code == 415 or exc.code == 400:
            return (
                jsonify(core.error_envelope(core.ERR_INVALID_REQUEST, exc.description or "Bad request.")),
                exc.code,
            )
        return exc
    app.logger.exception("unhandled error")
    return (
        jsonify(core.error_envelope(core.ERR_INVALID_REQUEST, "The request could not be processed.")),
        400,
    )


@app.get("/_health")
def health():
    return jsonify({"status": "ok"}), 200


routes.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)