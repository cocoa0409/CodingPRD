"""Entry point for the Digital MSK Program Enrollment & Outcome Fees API.

Boots a Flask server on 0.0.0.0:$PORT (default 10000).  Storage is in-memory
only and starts empty: nothing here seeds, preloads or registers any entity.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify  # noqa: E402

from db import STORE  # noqa: E402
from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402
from routes import (  # noqa: E402
    clients,
    enrollment,
    outcomes,
    roster,
    sessions,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(roster.bp)
app.register_blueprint(enrollment.bp)
app.register_blueprint(sessions.bp)
app.register_blueprint(outcomes.bp)
app.register_blueprint(clients.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def handle_not_found(error):
    return error_response(
        "ERR_RESOURCE_NOT_FOUND", "No such endpoint on this API.", 404
    )


@app.errorhandler(405)
def handle_method(error):
    return error_response(
        "ERR_RESOURCE_NOT_FOUND", "That method is not allowed on this path.", 404
    )


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return error_response(error.error_id, error.message, error.http_status)
    code = getattr(error, "code", None)
    if isinstance(code, int) and 400 <= code < 500:
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", str(error), code
        )
    app.logger.exception("unhandled error")
    return error_response("ERR_INVALID_STATE", str(error), 500)


@app.before_request
def _guard_state():
    # The store is per-process and in-memory; nothing is persisted anywhere.
    STORE.lock.acquire()


@app.after_request
def _release_state(response):
    try:
        STORE.lock.release()
    except RuntimeError:
        pass
    return response


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)