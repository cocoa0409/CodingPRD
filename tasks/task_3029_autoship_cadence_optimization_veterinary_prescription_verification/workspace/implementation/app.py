"""Application entry point.

Boots a Flask server on 0.0.0.0:$PORT (default 10000) in the foreground.
The in-memory store starts EMPTY: nothing is seeded, preloaded or hardcoded,
so a fresh process always begins from the declared API surface alone.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from middleware import enforce_before_routing
from response import error_body
import routing

# Importing the route modules registers their handlers in routing.ROUTES.
import routes.catalog  # noqa: F401
import routes.ops  # noqa: F401
import routes.orders  # noqa: F401
import routes.pets  # noqa: F401
import routes.plans  # noqa: F401
import routes.prescriptions  # noqa: F401
import routes.reviews  # noqa: F401

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return error_body(
            "ERR_RESOURCE_NOT_FOUND", "The requested path does not exist.", 404
        )
    if exc.code == 405:
        return error_body(
            "ERR_ROLE_NOT_PERMITTED", "The HTTP method is not allowed here.", 405
        )
    return error_body("ERR_INVALID_REQUEST", exc.description, exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_body("ERR_INVALID_REQUEST", str(exc), 400)


routing.register_all(app)


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.before_request
def _authenticate_before_routing():
    return enforce_before_routing()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
    )