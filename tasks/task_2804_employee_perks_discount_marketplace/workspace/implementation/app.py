"""Employee Perks & Discount Marketplace API.

Storage is entirely in-memory and starts EMPTY on every boot: no entity is ever
seeded, preloaded or hardcoded here. Every row a caller sees was created through
the declared API surface of PRD 4.
"""
import os

from flask import Flask

import response
import routes
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

routes.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return response.error("ERR_NOT_FOUND", "No such route.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return response.error("ERR_METHOD_NOT_ALLOWED",
                          "That method is not allowed on this route.", 405)


@app.errorhandler(400)
def handle_bad_request(exc):
    return response.error("ERR_VALIDATION", "The request body is malformed.", 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error")
    return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
