"""Application entry point: Flask app, route registration, error handlers."""

import os

from flask import Flask

import envelope
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

register_routes(app)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope.error(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return envelope.error(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return envelope.error(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(400)
def handle_bad_request(e):
    return envelope.error(ERR_INVALID_REQUEST, 400, "bad request")


@app.errorhandler(500)
def handle_internal_error(e):
    return envelope.error(ERR_INVALID_REQUEST, 500, "internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
