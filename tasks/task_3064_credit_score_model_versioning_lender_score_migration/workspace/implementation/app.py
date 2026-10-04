"""Credit Score Model Versioning API -- application entry point.

Python + Flask. Storage is in-memory only and the store starts empty on every
boot: nothing is seeded, preloaded or hardcoded. Every entity a client needs is
constructed through the declared API surface.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from core import error_body
from errors import ApiError, ERROR_STATUS
from routes import BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    status = exc.http_status or ERROR_STATUS.get(exc.error_id, 400)
    return jsonify(error_body(exc.error_id, exc.message)), status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    error_id = "ERR_INVALID_REQUEST"
    if exc.code == 404:
        error_id = "ERR_INVALID_REQUEST"
    if exc.code == 405:
        error_id = "ERR_INVALID_REQUEST"
    return jsonify(error_body(error_id, exc.description or "The request could not be completed.")), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 400


@app.errorhandler(404)
def handle_404(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "No route matches the request.")), 404


@app.errorhandler(400)
def handle_400(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "The request body is malformed.")), 400


@app.errorhandler(500)
def handle_500(exc):
    return jsonify(error_body("ERR_INVALID_REQUEST", "The request could not be completed.")), 500


@app.route("/", methods=["GET"])
def root():
    return jsonify({"meta": {"api_request_id": "req_ROOT", "api_request_timestamp": None},
                    "response_type": "object",
                    "data": {"service": "credit-score-model-versioning"}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))