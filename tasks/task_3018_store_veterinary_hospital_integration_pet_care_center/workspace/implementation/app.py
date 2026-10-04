"""Store Veterinary Pet Care Center API — Flask entry point.

The store starts empty on every boot: no entity is seeded, preloaded or
registered at startup, and nothing is persisted to disk. Every test builds
its own state through the declared API surface.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import response  # noqa: E402
from errors import ApiError  # noqa: E402
from services import core  # noqa: E402

from routes import bookings, clinics, hospital, packages, stores  # noqa: E402

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for module in (stores, bookings, hospital, clinics, packages):
    app.register_blueprint(module.bp)


@app.before_request
def _revalidate_deadlines():
    """Every request is evaluated against the current logical clock."""
    if request.path != "/_clock/set_current_utc":
        core.sweep_due_actions()


@app.errorhandler(ApiError)
def _api_error(exc):
    payload, _ = response.error(exc.error_id, exc.message)
    return jsonify(payload), exc.http_status


@app.errorhandler(HTTPException)
def _http_error(exc):
    mapping = {404: ("ERR_INVALID_REQUEST", 400), 405: ("ERR_INVALID_REQUEST", 400)}
    error_id, status = mapping.get(exc.code, ("ERR_INVALID_REQUEST", exc.code or 400))
    payload, _ = response.error(error_id, exc.description)
    return jsonify(payload), status


@app.errorhandler(Exception)
def _unexpected(exc):
    payload, _ = response.error("ERR_INVALID_REQUEST", str(exc))
    return jsonify(payload), 400


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"meta": response.meta(), "response_type": "object",
                    "data": {"status": "ok"}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)