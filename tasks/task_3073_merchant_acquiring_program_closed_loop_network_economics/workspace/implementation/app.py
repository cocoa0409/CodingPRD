"""Merchant Acquiring Closed-Loop Network API — entry point.

All state is held in process memory; the store starts empty on every boot and
nothing is seeded here.  Every entity a client needs is constructed through the
declared endpoints.
"""

import os
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ERR_INVALID_REQUEST, ApiError
from response import error_response

API_PREFIX = "/network"

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def register_blueprints(flask_app):
    from routes import cardmembers, complaints, disputes, merchants, offers, settlements
    from routes import system

    flask_app.register_blueprint(system.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(merchants.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(offers.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(cardmembers.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(settlements.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(disputes.bp, url_prefix=API_PREFIX)
    flask_app.register_blueprint(complaints.bp, url_prefix=API_PREFIX)


register_blueprints(app)


@app.errorhandler(ApiError)
def handle_api_error(error):
    body, _ = error_response(error.error_id, error.message)
    return body, error.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    if error.code == 405:
        body, _ = error_response(ERR_INVALID_REQUEST, "The method is not allowed here.")
        return body, 405
    if error.code == 415:
        body, _ = error_response(ERR_INVALID_REQUEST, "Unsupported media type.")
        return body, 415
    body, _ = error_response(ERR_INVALID_REQUEST, error.description or "Request failed.")
    return body, error.code


@app.errorhandler(Exception)
def handle_unexpected(error):
    traceback.print_exc()
    body, _ = error_response(ERR_INVALID_REQUEST, "The request could not be processed.")
    return body, 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.before_request
def _touch():
    # Nothing is cached between requests; the logical clock is server-owned.
    request.environ.setdefault("network.api_prefix", API_PREFIX)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)