"""Entry point: error handlers and route registration.

The store starts empty on every boot.  Nothing here (and nothing in any module
imported by it) seeds, preloads or registers an entity: every row a caller sees
was created through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from response import ApiError, Err, error_response
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    if err.code == 404:
        return error_response(ApiError(Err.RESOURCE_NOT_FOUND))
    if err.code == 405:
        return error_response(ApiError(Err.INVALID_REQUEST,
                                       "The method is not allowed on this path."))
    return error_response(ApiError(Err.INVALID_REQUEST, err.description))


@app.errorhandler(Exception)
def handle_unexpected(err):
    app.logger.exception("unhandled error: %s", err)
    return error_response(ApiError(Err.INVALID_REQUEST,
                                   "The request could not be processed."))


register_all(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)