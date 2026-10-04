# Entry point: Flask app assembly, error handlers, route registration.

import os

from flask import Flask

from errors import ApiError
from util import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", "malformed request"))


import routes_core
import routes_negotiation
import routes_premiere
import routes_release
import routes_awards
import routes_statements

routes_core.register(app)
routes_negotiation.register(app)
routes_premiere.register(app)
routes_release.register(app)
routes_awards.register(app)
routes_statements.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
