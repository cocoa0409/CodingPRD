"""Imaging Facility Accreditation API — application entry point.

In-memory only.  The store starts empty on every boot; nothing is seeded,
preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import (
    clock,
    cycles,
    facilities,
    phantom,
    plans,
    qualifications,
    registry,
    submissions,
    surveys,
    units,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

# Every boot starts from a clean slate.
db.reset()


def _register_routes():
    facilities.register_routes(app)
    units.register_routes(app)
    submissions.register_routes(app)
    phantom.register_routes(app)
    surveys.register_routes(app)
    qualifications.register_routes(app)
    plans.register_routes(app)
    cycles.register_routes(app)
    registry.register_routes(app)
    clock.register_routes(app)


_register_routes()


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.err(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    return response.err("ERR_INVALID_REQUEST", exc.description, exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return response.err("ERR_INVALID_REQUEST", str(exc), 400)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return response.err("ERR_INVALID_REQUEST", "method not allowed", 405)


@app.after_request
def identify(resp):
    resp.headers["X-Api-Server"] = "imaging-facility-accreditation"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)