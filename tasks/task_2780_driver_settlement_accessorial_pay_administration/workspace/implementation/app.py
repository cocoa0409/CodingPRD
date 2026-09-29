"""Driver Settlement and Accessorial Pay Administration API.

The store is empty on every boot: no entity is seeded, preloaded or hardcoded.
Every record is created by an API call.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import accessorials
from routes import advances
from routes import clock_routes
from routes import disputes
from routes import drivers
from routes import loads
from routes import pay_packages
from routes import retro
from routes import settlements

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

for module in (
    clock_routes,
    pay_packages,
    drivers,
    loads,
    accessorials,
    advances,
    settlements,
    disputes,
    retro,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )
    if exc.code == 405:
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this resource.", 405
        )
    if exc.code == 400:
        return response.error_response(
            "ERR_INVALID_FIELD_VALUE", "The request body could not be parsed.", 422
        )
    return response.error_response(
        "ERR_INVALID_FIELD_VALUE", exc.description or "Request rejected.", exc.code or 400
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return response.error_response("ERR_INVALID_FIELD_VALUE", str(exc), 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
