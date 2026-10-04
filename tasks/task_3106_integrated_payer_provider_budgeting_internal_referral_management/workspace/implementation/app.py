"""Flask entry point for the Integrated Payer-Provider Budgeting API.

The store starts empty on every boot: no seeding, no preloading, no disk
state. Every entity is created through the declared API surface.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from clock import CLOCK
from errors import ApiError
from response import error_body
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "logical_clock": CLOCK.now_iso()})


@app.errorhandler(ApiError)
def handle_api_error(error):
    return jsonify(error_body(error.error_id, error.message)), error.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    status = error.code or 500
    return jsonify(error_body(
        "ERR_HTTP_%d" % status,
        error.description or "The request could not be completed.")), status


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return jsonify(error_body(error.error_id, error.message)), error.http_status
    return jsonify(error_body(
        "ERR_INTERNAL_ERROR",
        "The request could not be completed.")), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)