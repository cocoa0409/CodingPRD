"""Entry point.

The store starts EMPTY on every boot — no seeding, no preloading, no hardcoded
entities. Every row a test needs is created through a declared endpoint.
"""

import os

from flask import Flask, request

import db
import middleware
import response
import routes
from errors import ApiError

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
# Requests from the harness reuse one process per boot; disable the strict slashes
# redirect so a trailing slash never turns into a 308.
app.url_map.strict_slashes = False

routes.register_all(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.envelope_error(err.error_id, err.message), err.http_status


@app.errorhandler(404)
def handle_not_found(err):
    return response.envelope_error("ERR_ENTITY_NOT_FOUND",
                                   "The requested path does not exist."), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return response.envelope_error("ERR_INVALID_REQUEST",
                                   "The method is not allowed for this path."), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    return response.envelope_error("ERR_INVALID_REQUEST", str(err)), 400


@app.route("/health", methods=["GET"])
def health():
    return response.envelope_object({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, use_reloader=False, threaded=True)