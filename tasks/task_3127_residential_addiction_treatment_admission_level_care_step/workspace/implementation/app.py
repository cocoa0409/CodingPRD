"""Entry point for the treatment-network API server."""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response
import db  # noqa: F401  (initialises the empty in-memory store)
import routes.changes
import routes.clinical
import routes.episodes
import routes.facilities
import routes.people

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes.facilities.bp, url_prefix="/treatment-network")
app.register_blueprint(routes.people.bp, url_prefix="/treatment-network")
app.register_blueprint(routes.episodes.bp, url_prefix="/treatment-network")
app.register_blueprint(routes.clinical.bp, url_prefix="/treatment-network")
app.register_blueprint(routes.changes.bp, url_prefix="/treatment-network")


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response("ERR_INVALID_REQUEST", "The requested path is not declared by this API.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response("ERR_INVALID_REQUEST", "The method is not declared for this path.", 405)


@app.errorhandler(500)
def handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)


@app.errorhandler(Exception)
def handle_generic(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code)
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)


@app.before_request
def _nothing():
    return None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)